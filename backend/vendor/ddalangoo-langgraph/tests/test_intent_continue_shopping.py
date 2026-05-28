"""
continue_shopping 상태의 의도 보정 테스트.

LLM이 pending_action 문맥 때문에 "오이도 담아줘"를 confirm으로 오판해도
새 상품 검색으로 돌아가도록 intent_agent의 deterministic 보정 로직을 검증한다.
"""
from src.agents import intent_agent
from src.agents.intent_agent import IntentOutput, intent_agent_node
from src.state.schema import get_default_shopping_state


class _FakeStructuredLlm:
    def __init__(self, output: IntentOutput):
        self._output = output

    def invoke(self, _messages):
        return self._output


def _make_state(user_input: str) -> dict:
    state = get_default_shopping_state("user_test", "session_test")
    state.update(
        {
            "stage": "cart_shopping",
            "pending_action": {"type": "continue_shopping"},
            "keywords": ["토마토"],
            "quantity": 1,
            "messages": [{"role": "user", "content": user_input}],
        }
    )
    return state


def test_continue_shopping_product_addition_overrides_confirm(monkeypatch):
    """오이도 담아줘 → 결제 confirm이 아니라 새 buy intent + 오이 keyword."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="confirm", keywords=["토마토"])),
    )

    result = intent_agent_node(_make_state("오이도 담아줘"))

    assert result["intent"] == "buy"
    assert result["keywords"] == ["오이"]
    assert result["quantity"] is None
    assert result["needs_clarification"] is False


def test_continue_shopping_payment_confirmation_clears_stale_keywords(monkeypatch):
    """결제할래 → 이전 토마토 keyword를 들고 검색으로 가지 않고 결제로 간다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="buy", keywords=["토마토"])),
    )

    result = intent_agent_node(_make_state("결제할래"))

    assert result["intent"] == "confirm"
    assert result["keywords"] == []
    assert result["needs_clarification"] is False
