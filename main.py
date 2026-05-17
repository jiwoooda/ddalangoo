"""
LangGraph Shopping Assistant — Baseline Entry Point.

graph.invoke() 기반 REPL 루프.
interrupt_before=["wait_for_input"] 기반 human-in-the-loop.

사용법:
    python main.py
    python main.py --user user_001 --thread thread_001
"""
import argparse
import uuid
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# ANTHROPIC_API_KEY 확인
if not os.getenv("ANTHROPIC_API_KEY"):
    print("[경고] ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.")
    print("       LLM 호출이 필요한 기능은 동작하지 않습니다.")
    print("       .env 파일을 생성하거나 환경 변수를 설정하세요.\n")

from src.graph.builder import build_graph
from src.state.schema import get_default_shopping_state


def run_session(user_id: str = "user_test", thread_id: str = None):
    """단일 대화 세션 실행."""
    if thread_id is None:
        thread_id = str(uuid.uuid4())

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n=== 쇼핑 어시스턴트 시작 ===")
    print(f"user_id: {user_id} | thread_id: {thread_id}")
    print("종료하려면 'exit' 또는 Ctrl+C를 입력하세요.\n")

    graph = build_graph()

    # 초기 state 설정 후 wait_for_input에서 interrupt 대기
    initial_state = get_default_shopping_state(user_id, session_id)
    graph.invoke(initial_state, config)

    # 대화 루프
    while True:
        try:
            current = graph.get_state(config)

            # 그래프가 완전히 종료된 경우
            if not current.next:
                print("\n[세션 종료]")
                break

            # 다음 노드가 wait_for_input이면 사용자 입력 대기
            if "wait_for_input" in current.next:
                user_input = input("사용자: ").strip()
                if user_input.lower() in ("exit", "quit"):
                    print("[대화 종료]")
                    break

                # 사용자 메시지를 state에 주입하고 재개
                graph.update_state(
                    config,
                    {"messages": [{"role": "user", "content": user_input}]},
                )
                _invoke_and_print(graph, None, config)
            else:
                # 다른 노드가 next인 경우 (예: END에 도달하기 전)
                graph.invoke(None, config)
                current = graph.get_state(config)
                if not current.next:
                    print("\n[세션 종료]")
                    break

        except KeyboardInterrupt:
            print("\n[중단됨]")
            break
        except Exception as e:
            print(f"[오류] {e}")
            break


def _invoke_and_print(graph, state, config):
    """graph.invoke() 실행 후 마지막 assistant 메시지 출력."""
    try:
        result = graph.invoke(state, config)
    except Exception as e:
        print(f"[그래프 오류] {e}")
        return

    current = graph.get_state(config)
    messages = current.values.get("messages", [])

    # 마지막 assistant 메시지 출력
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "assistant":
                print(f"어시스턴트: {msg['content']}\n")
                break
        else:
            role = getattr(msg, "type", None)
            if role == "ai":
                print(f"어시스턴트: {msg.content}\n")
                break

    # 디버그: 현재 stage
    stage = current.values.get("stage", "unknown")
    pending = current.values.get("pending_action")
    print(f"  [stage: {stage}", end="")
    if pending:
        print(f" | pending: {pending.get('type')}", end="")
    print("]")


def run_demo():
    """API key 없이 라우터/플로우만 검증하는 데모."""
    print("\n=== Demo Mode (LLM 없이 라우터/플로우 검증) ===\n")

    from src.graph.router import route, after_respond
    from src.state.schema import get_default_shopping_state
    from src.payment.flow import payment_flow

    # 1. Router 테스트
    print("--- Router 테스트 ---")
    cases = [
        {"intent": "buy", "stage": "idle", "confidence": 0.9, "needs_clarification": False},
        {"intent": "confirm", "stage": "product_confirming", "confidence": 0.9, "needs_clarification": False},
        {"intent": "cancel", "stage": "payment_processing", "confidence": 0.9, "needs_clarification": False},
        {"intent": "unclear", "stage": "idle", "confidence": 0.3, "needs_clarification": True},
        {"intent": "option_select", "stage": "payment_processing", "confidence": 0.9, "needs_clarification": False},
    ]
    for case in cases:
        state = get_default_shopping_state("user_test", "sess")
        state.update(case)
        result = route(state)
        print(f"  {case['intent']} + {case['stage']} → {result}")

    # 2. Payment Flow 테스트
    print("\n--- Payment Flow 테스트 ---")
    payment_state = {
        "user_id": "user_test",
        "conversation_id": None,
        "selected_product": {
            "product_name": "사과 1kg",
            "price": 9900,
            "platform": "naver",
            "product_url": "https://mock.naver.com/apple",
        },
        "product_url": "https://mock.naver.com/apple",
        "quantity": 1,
        "selected_platform": "naver",
        "available_options": [],
        "current_option_index": 0,
        "current_option_key": None,
        "current_option_value": None,
        "selected_options": {},
        "delivery_address": {
            "address_line1": "서울 강남구 테헤란로 123",
            "recipient_name": "테스트유저",
        },
        "address_confirmed": True,
        "playwright_session": None,
        "checkout_session_id": None,
        "order_id": None,
        "payment_stage": "validate_input",
        "payment_status": "pending",
        "payment_step": None,
        "payment_retry": 0,
        "payment_error": None,
        "pending_action": None,
    }

    result = payment_flow(payment_state)
    print(f"  payment_stage: {result['payment_stage']}")
    print(f"  payment_status: {result['payment_status']}")
    print(f"  pending_action.type: {result.get('pending_action', {}).get('type') if result.get('pending_action') else None}")
    print(f"  order_id: {result.get('order_id')}")

    print("\n[Demo 완료]")


def main():
    parser = argparse.ArgumentParser(description="LangGraph Shopping Assistant")
    parser.add_argument("--user", default="user_test", help="사용자 ID")
    parser.add_argument("--thread", default=None, help="스레드 ID")
    parser.add_argument("--demo", action="store_true", help="LLM 없이 데모 실행")
    args = parser.parse_args()

    if args.demo or not os.getenv("ANTHROPIC_API_KEY"):
        run_demo()
    else:
        run_session(user_id=args.user, thread_id=args.thread)


if __name__ == "__main__":
    main()
