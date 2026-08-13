"""프론트엔드 가입 이름 -> 스몰톡 온보딩 연결(브릿지) 확인용 인터랙티브 REPL.

smalltalk_agent_node를 직접 부르지 않고 실제 컴파일된 그래프(build_graph)를
그대로 태운다 — 그래야 세션이 열리자마자 session_start/route_session_start가
신규·미온보딩 유저에게 딸랑구의 선제 인사를 트리거하는 부분까지 실제
운영과 동일하게 확인할 수 있다.

가입 시 이름을 받아둔 것처럼(mock_tools.MOCK_USERS) 시뮬레이션한 뒤,
backend/app/agent/runtime.py의 _seed_preferred_name_if_new를 실제로 호출해서
profile.preferred_name을 미리 채운다. 그다음:
1. 그래프를 신규 세션으로 invoke — 딸랑구가 사용자 입력 없이 먼저 말을
   거는지(session_start) 확인.
2. 그 첫 인사가 이름을 또 안 묻고 이미 아는 이름으로 바로 인사하는지 확인.

Postgres 없이 DB_MODE=mock으로 동작한다.

실행:
    python tests/test_frontend_name_bridge.py
    python tests/test_frontend_name_bridge.py --user user_test --model gpt-4o-mini

mock 유저 목록(src/tools/mock_tools.py MOCK_USERS, 구매이력 0건인 것만 신규
유저로 판정됨): "user_test"(테스트유저), "demo"(데모유저) — "1"/"user_001"은
mock 구매이력이 있어서 기존 유저로 판정되니 이 테스트엔 안 맞음.

명령어: /profile  /reset  /quit
"""

import argparse
import os
import sys
import uuid

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# backend/app이 "app" 패키지 자체(backend/app/__init__.py)이므로, import app...
# 이 되려면 그 부모인 backend/를 path에 넣어야 한다.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, _BACKEND_DIR)
load_dotenv()


def _ensure_langgraph_compatibility() -> None:
    """구버전 개발 환경에서도 스몰토크 노드를 직접 불러올 수 있게 한다."""
    import langgraph.errors

    if not hasattr(langgraph.errors, "NodeError"):
        class NodeError(Exception):
            pass

        langgraph.errors.NodeError = NodeError


def _last_ai_message(graph, config) -> str | None:
    vals = graph.get_state(config).values
    for msg in reversed(vals.get("messages", [])):
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role in ("ai", "assistant"):
            return getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
    return None


def _print_reply(reply: str | None) -> None:
    if reply is None:
        print("\n[안내] 이번 턴엔 딸랑구가 먼저 말하지 않았습니다(기존/온보딩완료 유저로 판정됐을 수 있음).")
        return
    question_count = reply.count("?") + reply.count("？")
    print(f"\n딸랑구 > {reply}")
    print(f"  └─ 물음표={question_count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="프론트 가입 이름 -> 스몰톡 연결 확인 (전체 그래프)")
    parser.add_argument("--model", default="gpt-4o-mini", help="스몰토크에 사용할 모델(기본: gpt-4o-mini)")
    parser.add_argument("--user", default="user_test", help="mock 유저 ID (기본: user_test, 테스트유저)")
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
    from app.agent.runtime import _seed_preferred_name_if_new

    user_id = args.user

    def seed() -> None:
        db_client.save_profile(user_id, {})  # 재실행 대비 깨끗한 상태에서 시작
        _seed_preferred_name_if_new(user_id)

    known_user = db_client.get_user(user_id)
    print("=" * 64)
    print("  프론트 가입 이름 -> 스몰톡 온보딩 연결 확인 (전체 그래프)")
    print(f"  user_id={user_id} | mock 가입 정보: {known_user}")
    print("=" * 64)

    if not known_user or not known_user.get("name"):
        print(f"[안내] user_id={user_id}에 mock 가입 이름이 없습니다.")
        print('  mock_tools.MOCK_USERS에 등록된 ID를 쓰세요: "user_test", "demo"')
        return

    graph = build_graph()

    def start_new_session() -> None:
        nonlocal config
        seed()
        thread_id = f"name-bridge-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = get_default_shopping_state(user_id, thread_id)
        graph.invoke(initial_state, config)  # session_start -> (신규유저면) smalltalk_agent 선제 인사

    config: dict = {}
    start_new_session()
    profile_after_seed = db_client.get_profile(user_id) or {}
    print(f"[시드 완료] profile.preferred_name = {profile_after_seed.get('preferred_name')!r}")
    print("  (아래가 세션이 열리자마자 딸랑구가 먼저 건넨 첫 인사입니다)")
    _print_reply(_last_ai_message(graph, config))
    print(f"\n  model={args.model} | /profile  /reset  /quit")
    print("=" * 64)

    while True:
        try:
            user_input = input("\n사용자 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_input:
            continue
        if user_input.startswith("/"):
            command = user_input.lower()
            if command in ("/quit", "/exit", "/q"):
                print("종료합니다.")
                break
            if command == "/profile":
                print(db_client.get_profile(user_id))
                continue
            if command == "/reset":
                start_new_session()
                print("새 세션 시작 + 이름 재시드 완료.")
                _print_reply(_last_ai_message(graph, config))
                continue
            print("알 수 없는 명령입니다: /profile /reset /quit")
            continue

        try:
            graph.update_state(config, {"messages": [{"role": "user", "content": user_input}]})
            graph.invoke(None, config)
        except Exception as exc:
            print(f"\n[호출 실패] {type(exc).__name__}: {exc}")
            continue

        _print_reply(_last_ai_message(graph, config))

        vals = graph.get_state(config).values
        if vals.get("onboarding_started_at") is None:
            print("  └─ 온보딩 완료 상태입니다. 계속 시험하거나 /reset 할 수 있습니다.")


if __name__ == "__main__":
    main()
