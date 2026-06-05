from src.agents.memory_agent import memory_agent_node
from src.state.schema import get_default_shopping_state


def test_memory_agent_completed_does_not_emit_purchase_history_tool_call():
    """구매이력 저장 책임은 payment_service에 있고 memory_agent는 저장 tool을 만들지 않는다."""
    state = get_default_shopping_state("6", "session-test")
    state.update(
        {
            "stage": "completed",
            "conversation_id": 125,
            "messages": [{"role": "user", "content": "결제 완료"}],
            "order": {"orderId": 77},
            "payment": {"paymentId": 88},
        }
    )

    result = memory_agent_node(state)

    tool_calls = result.get("tool_calls") or []
    assert all(call.get("tool") != "save_purchase_history" for call in tool_calls)
