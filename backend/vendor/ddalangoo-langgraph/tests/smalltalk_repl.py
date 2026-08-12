"""Smalltalk Agent 인터랙티브 REPL.

실행:
    python tests/smalltalk_repl.py
    python tests/smalltalk_repl.py --model gpt-4o-mini --debug

명령:
    /status   현재 조건부 조각 상태 출력
    /profile  지금까지 저장된 mock 프로필 출력
    /reset    대화와 프로필 초기화
    /quit     종료
"""

import argparse
import json
import os
import sys
import uuid

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
    print(f"  onboarding_active     : {state.get('onboarding_started_at') is not None}\n")


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

    print("=" * 64)
    print("  Smalltalk Agent REPL — 실제 LLM과 온보딩 대화")
    print(f"  model={args.model} | user={user_id} | DB=mock")
    print(f"  provider={'OpenAI' if args.model.startswith('gpt') else 'Anthropic'}")
    print("  /status  /profile  /reset  /quit")
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
            if command == "/status":
                _print_status(state)
                continue
            if command == "/profile":
                print(json.dumps(db_client.get_profile(user_id) or {}, ensure_ascii=False, indent=2))
                continue
            if command == "/reset":
                db_client.save_profile(user_id, {})
                state = _new_state(user_id)
                print("대화와 mock 프로필을 초기화했습니다.")
                continue
            print("알 수 없는 명령입니다: /status /profile /reset /quit")
            continue

        state["messages"].append({"role": "user", "content": user_input})
        try:
            result = smalltalk_agent_node(state)
        except Exception as exc:
            print(f"\n[호출 실패] {type(exc).__name__}: {exc}")
            state["messages"].pop()  # 실패한 사용자 입력은 다음 시도 이력에서 제외
            continue


        if result.get("degraded_mode"):
            _print_degraded_error(result, args.model)
            state["messages"].pop()  # fallback을 대화로 소비하지 않고 같은 턴 재시도 허용
            continue

        reply = result["immediate_response"]
        state.update(result)
        state["messages"].append({"role": "assistant", "content": reply})

        question_count = reply.count("?") + reply.count("？")
        print(f"\n딸랑구 > {reply}")
        print(f"  └─ 질문 수={question_count}")
        if args.debug:
            _print_status(state)

        if state.get("onboarding_started_at") is None:
            print("  └─ 온보딩 완료 상태입니다. 계속 시험하거나 /reset 할 수 있습니다.")


if __name__ == "__main__":
    main()
