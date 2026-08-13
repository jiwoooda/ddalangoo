"""Smalltalk Agent 인터랙티브 REPL.

실행:
    python tests/smalltalk_repl.py
    python tests/smalltalk_repl.py --model gpt-4o-mini --debug

명령:
    /status   현재 조건부 조각 상태 출력
    /profile  지금까지 저장된 mock 프로필 출력
    /save     지금까지의 대화+프로필을 즉시 파일로 저장(종료 안 해도 됨)
    /reset    대화와 프로필 초기화(초기화 전 지금까지 대화는 자동 저장됨)
    /quit     종료(종료 시 지금까지 대화 자동 저장)

test_smalltalk_recorded_flow.py와 같은 형식(대화 turn별 내역 + 최종 profile)으로
logs/smalltalk_test_runs/repl_run_<timestamp>.json에 저장한다 — 스크립트로 미리
짠 시나리오가 아니라 직접 타이핑하며 테스트한 대화도 나중에 다시 열어보거나
비교할 수 있게 남기기 위함.
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


def _ensure_langgraph_compatibility() -> None:
    """구버전 개발 환경에서도 스몰토크 노드를 직접 불러올 수 있게 한다."""
    import langgraph.errors

    if not hasattr(langgraph.errors, "NodeError"):
        class NodeError(Exception):
            pass

        langgraph.errors.NodeError = NodeError


def _new_state(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "messages": [],
        "onboarding_started_at": None,
        "recent_patterns_used": [],
        "recent_episodes_used": [],
        "consecutive_question_turns": 0,
        "name_greeting_pending": False,
        "already_asked_topics": [],
    }


def _print_status(state: dict) -> None:
    print("\n[상태]")
    print(f"  name_greeting_pending : {state.get('name_greeting_pending', False)}")
    print(f"  recent_patterns       : {state.get('recent_patterns_used') or []}")
    print(f"  recent_episodes       : {state.get('recent_episodes_used') or []}")
    print(f"  consecutive_questions : {state.get('consecutive_question_turns', 0)}")
    print(f"  already_asked_topics  : {state.get('already_asked_topics') or []}")
    print(f"  turns_without_progress: {state.get('turns_without_required_progress', 0)}")
    print(f"  health_followup_left  : {state.get('health_followup_turns_remaining', 0)}")
    print(f"  onboarding_active     : {state.get('onboarding_started_at') is not None}\n")


def _save_transcript(user_id: str, model: str, conversation: list[dict]) -> str | None:
    """test_smalltalk_recorded_flow.py와 같은 파일 형식으로 저장한다.
    빈 대화(턴 없이 바로 /quit 등)는 저장하지 않는다 — 반환값 None."""
    if not conversation:
        return None
    from src.tools import db_client
    from src.agents.smalltalk_agent import REQUIRED_FIELDS

    final_profile = db_client.get_profile(user_id) or {}
    required_filled = {f: final_profile.get(f) for f in sorted(REQUIRED_FIELDS)}
    required_filled_count = sum(1 for v in required_filled.values() if v not in (None, [], ""))

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "user_id": user_id,
        "source": "smalltalk_repl",
        "conversation": conversation,
        "final_profile": final_profile,
        "required_fields_status": required_filled,
        "required_fields_filled_count": f"{required_filled_count}/{len(REQUIRED_FIELDS)}",
    }

    out_dir = os.path.join(os.path.dirname(__file__), "..", "logs", "smalltalk_test_runs")
    os.makedirs(out_dir, exist_ok=True)
    out_name = f"repl_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = os.path.abspath(os.path.join(out_dir, out_name))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return out_path


def _print_degraded_error(result: dict, model: str) -> None:
    """fallback을 정상 대화처럼 보이지 않게 명확한 테스트 실패로 표시한다."""
    print("\n[LLM 호출 실패 — 아래 문장은 실제 모델 응답이 아닙니다]")
    print(f"  model      : {model}")
    print(f"  stage      : {result.get('failure_stage') or 'unknown'}")
    print(f"  reason     : {result.get('degradation_reason') or 'unknown'}")
    print(f"  fallback   : {result.get('immediate_response')}")
    print("  .env의 API 키·모델 접근 권한을 확인하거나 --model로 다른 모델을 지정하세요.")
    print("  예: python tests/smalltalk_repl.py --model gpt-4o-mini --debug")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smalltalk Agent 실제 LLM 대화 테스트")
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="스몰토크에 사용할 모델(기본: gpt-4o-mini)",
    )
    parser.add_argument("--user", default=None, help="mock 프로필 사용자 ID")
    parser.add_argument("--debug", action="store_true", help="매 턴 내부 상태 출력")
    args = parser.parse_args()

    # 프로젝트 .env의 CONTEXT_MODEL이 Claude로 설정돼 있어도 이 독립 REPL은
    # OpenAI로 바로 실행되는 것이 기본이다. 다른 모델은 --model로만 선택한다.
    os.environ["LLM_BACKEND"] = "api"
    os.environ["CONTEXT_MODEL"] = args.model
    os.environ["DB_MODE"] = "mock"

    if args.model.startswith("gpt") and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 설정되지 않았습니다. .env를 확인하세요.")
    if not args.model.startswith("gpt") and not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env를 확인하세요.")

    _ensure_langgraph_compatibility()
    from src.agents.smalltalk_agent import smalltalk_agent_node
    from src.tools import db_client

    user_id = args.user or f"smalltalk_repl_{uuid.uuid4().hex[:8]}"
    state = _new_state(user_id)
    conversation: list[dict] = []
    turn = 0

    print("=" * 64)
    print("  Smalltalk Agent REPL — 실제 LLM과 온보딩 대화")
    print(f"  model={args.model} | user={user_id} | DB=mock")
    print(f"  provider={'OpenAI' if args.model.startswith('gpt') else 'Anthropic'}")
    print("  /status  /profile  /save  /reset  /quit")
    print("=" * 64)

    # 실제 그래프는 신규유저 진입 시 session_start 노드가 사용자 발화 없이
    # smalltalk_agent를 먼저 호출해 선제 인사를 띄운다(route_session_start).
    # 이 REPL은 smalltalk_agent_node를 그래프 없이 직접 호출하므로 그 경로를
    # 안 타서, 메시지가 하나도 없는 상태로 여기서 한 번 먼저 호출해 같은
    # 상황(딸랑구가 먼저 말을 거는 것)을 재현한다 — 안 하면 실제 서비스와
    # 달리 첫 턴부터 사용자가 먼저 말을 걸어야 하는 것처럼 보인다.
    try:
        greet_result = smalltalk_agent_node(state)
    except Exception as exc:
        print(f"\n[선제 인사 호출 실패] {type(exc).__name__}: {exc}")
    else:
        if greet_result.get("degraded_mode"):
            _print_degraded_error(greet_result, args.model)
        else:
            greeting = greet_result["immediate_response"]
            state.update(greet_result)
            state["messages"].append({"role": "assistant", "content": greeting})
            turn += 1
            conversation.append({"turn": turn, "speaker": "딸랑구(선제 인사)", "text": greeting})
            print(f"\n딸랑구 > {greeting}")
            if args.debug:
                _print_status(state)

    while True:
        try:
            user_input = input("\n사용자 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            saved = _save_transcript(user_id, args.model, conversation)
            if saved:
                print(f"대화 기록 저장: {saved}")
            break

        if not user_input:
            continue
        if user_input.startswith("/"):
            command = user_input.lower()
            if command in ("/quit", "/exit", "/q"):
                print("종료합니다.")
                saved = _save_transcript(user_id, args.model, conversation)
                if saved:
                    print(f"대화 기록 저장: {saved}")
                break
            if command == "/status":
                _print_status(state)
                continue
            if command == "/profile":
                print(json.dumps(db_client.get_profile(user_id) or {}, ensure_ascii=False, indent=2))
                continue
            if command == "/save":
                saved = _save_transcript(user_id, args.model, conversation)
                print(f"대화 기록 저장: {saved}" if saved else "저장할 대화가 아직 없습니다.")
                continue
            if command == "/reset":
                saved = _save_transcript(user_id, args.model, conversation)
                if saved:
                    print(f"초기화 전 대화 기록 저장: {saved}")
                db_client.save_profile(user_id, {})
                state = _new_state(user_id)
                conversation = []
                turn = 0
                print("대화와 mock 프로필을 초기화했습니다.")
                continue
            print("알 수 없는 명령입니다: /status /profile /save /reset /quit")
            continue

        turn += 1
        state["messages"].append({"role": "user", "content": user_input})
        try:
            result = smalltalk_agent_node(state)
        except Exception as exc:
            print(f"\n[호출 실패] {type(exc).__name__}: {exc}")
            state["messages"].pop()  # 실패한 사용자 입력은 다음 시도 이력에서 제외
            turn -= 1
            continue

        if result.get("degraded_mode"):
            _print_degraded_error(result, args.model)
            state["messages"].pop()  # fallback을 대화로 소비하지 않고 같은 턴 재시도 허용
            turn -= 1
            continue

        reply = result["immediate_response"]
        state.update(result)
        state["messages"].append({"role": "assistant", "content": reply})
        conversation.append({"turn": turn, "speaker": "사용자", "text": user_input})
        conversation.append({"turn": turn, "speaker": "딸랑구", "text": reply})

        question_count = reply.count("?") + reply.count("？")
        print(f"\n딸랑구 > {reply}")
        print(f"  └─ 질문 수={question_count}")
        if args.debug:
            _print_status(state)

        if state.get("onboarding_started_at") is None:
            print("  └─ 온보딩 완료 상태입니다. 계속 시험하거나 /reset 할 수 있습니다.")


if __name__ == "__main__":
    main()
