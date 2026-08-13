"""스몰톡 온보딩 대화 기록용 테스트 러너.

전체 그래프(build_graph)를 태워서 session_start의 선제 인사부터 온보딩
종료까지 실LLM으로 돌리고, 매 턴의 대화 내역과 최종 profile(스키마 채움
상태)을 JSON 파일로 저장한다 — 나중에 다시 열어보거나 여러 실행을 비교할
수 있게, 화면에 찍고 끝내는 대신 파일로 남긴다.

실행:
    python tests/test_smalltalk_recorded_flow.py
    python tests/test_smalltalk_recorded_flow.py --user user_test --out my_run.json
    python tests/test_smalltalk_recorded_flow.py --scripted "안녕하세요" "김철수예요" ...

기본 시나리오는 REQUIRED_FIELDS(food_dislikes/delivery_priority/
household_size/value_priority)를 포함해 profile 필드 대부분을 채우도록
설계된 8턴 대화다. --scripted로 직접 턴을 넘기면 그걸 대신 쓴다.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

_DEFAULT_TURNS = [
    "안녕하세요",
    "저는 김철수라고 해요",
    "요즘 소화가 잘 안돼서 매운 음식은 잘 못 먹어요",
    "쿠팡에서 주로 사요",
    "혼자 살고 있어요",
    "가성비가 좋으면 좋겠어요",
    "배송은 빠른 게 좋아요",
    "네 맞아요",
]


def _ensure_langgraph_compatibility() -> None:
    import langgraph.errors

    if not hasattr(langgraph.errors, "NodeError"):
        class NodeError(Exception):
            pass

        langgraph.errors.NodeError = NodeError


def _extract_reply(graph, config) -> tuple[str | None, str]:
    vals = graph.get_state(config).values
    for msg in reversed(vals.get("messages", [])):
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role in ("ai", "assistant"):
            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
            return content, vals.get("stage", "idle")
    return None, vals.get("stage", "idle")


def main() -> None:
    parser = argparse.ArgumentParser(description="스몰톡 온보딩 대화 기록 러너")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--user", default=None, help="mock 유저 ID (기본: 랜덤 신규 유저)")
    parser.add_argument("--scripted", nargs="*", default=None, help="직접 턴을 지정(생략하면 기본 8턴 시나리오)")
    parser.add_argument("--out", default=None, help="저장 파일명(생략하면 타임스탬프로 자동 생성)")
    args = parser.parse_args()

    os.environ["LLM_BACKEND"] = "api"
    os.environ["CONTEXT_MODEL"] = args.model
    os.environ["DB_MODE"] = "mock"

    if args.model.startswith("gpt") and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 설정되지 않았습니다. .env를 확인하세요.")
    if not args.model.startswith("gpt") and not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env를 확인하세요.")

    _ensure_langgraph_compatibility()
    from src.graph.builder import build_graph
    from src.state.schema import get_default_shopping_state
    from src.tools import db_client
    from src.agents.smalltalk_agent import REQUIRED_FIELDS

    user_id = args.user or f"recorded_{uuid.uuid4().hex[:8]}"
    thread_id = f"recorded-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    turns_to_send = args.scripted if args.scripted else _DEFAULT_TURNS

    graph = build_graph()
    initial_state = get_default_shopping_state(user_id, thread_id)
    graph.invoke(initial_state, config)  # session_start -> (신규유저면) 선제 인사

    conversation: list[dict] = []

    proactive_reply, proactive_stage = _extract_reply(graph, config)
    if proactive_reply:
        conversation.append({"turn": 0, "speaker": "딸랑구(선제 인사)", "text": proactive_reply})
        print(f"[Turn 0 - 선제 인사] 딸랑구: {proactive_reply}")

    for i, user_input in enumerate(turns_to_send, 1):
        graph.update_state(config, {"messages": [{"role": "user", "content": user_input}]})
        try:
            graph.invoke(None, config)
        except Exception as e:
            print(f"  [그래프 오류] {type(e).__name__}: {e}")
            conversation.append({"turn": i, "speaker": "사용자", "text": user_input})
            conversation.append({"turn": i, "speaker": "오류", "text": f"{type(e).__name__}: {e}"})
            break

        reply, stage = _extract_reply(graph, config)
        conversation.append({"turn": i, "speaker": "사용자", "text": user_input})
        conversation.append({"turn": i, "speaker": "딸랑구", "text": reply})
        print(f"\n[Turn {i}] 사용자: {user_input}")
        print(f"  딸랑구: {reply}")

        vals = graph.get_state(config).values
        if vals.get("onboarding_started_at") is None:
            print("  [온보딩 완료 — 이후 턴은 필요 없으면 중단 가능]")
            if not graph.get_state(config).next or vals.get("stage") in ("completed", "failed"):
                break

    final_profile = db_client.get_profile(user_id) or {}
    required_filled = {f: final_profile.get(f) for f in sorted(REQUIRED_FIELDS)}
    required_filled_count = sum(1 for v in required_filled.values() if v not in (None, [], ""))

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "user_id": user_id,
        "thread_id": thread_id,
        "turns_sent": turns_to_send,
        "conversation": conversation,
        "final_profile": final_profile,
        "required_fields_status": required_filled,
        "required_fields_filled_count": f"{required_filled_count}/{len(REQUIRED_FIELDS)}",
    }

    out_name = args.out or f"smalltalk_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_dir = os.path.join(os.path.dirname(__file__), "..", "logs", "smalltalk_test_runs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.abspath(os.path.join(out_dir, out_name))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 64)
    print(f"최종 profile: {final_profile}")
    print(f"필수 필드 충족: {record['required_fields_filled_count']} -> {required_filled}")
    print(f"저장 위치: {out_path}")
    print("=" * 64)


if __name__ == "__main__":
    main()
