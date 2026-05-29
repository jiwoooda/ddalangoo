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


def _make_what_to_buy_state(user_input: str) -> dict:
    state = _make_state(user_input)
    state["pending_action"] = {"type": "what_to_buy"}
    state["keywords"] = []
    state["quantity"] = None
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


def test_continue_shopping_ack_purchase_goes_to_checkout(monkeypatch):
    """응 구매해줘 → 응을 상품명으로 보지 않고 기존 장바구니 결제로 간다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="buy", keywords=["응"])),
    )

    result = intent_agent_node(_make_state("응 구매해줘"))

    assert result["intent"] == "confirm"
    assert result["keywords"] == []
    assert result["needs_clarification"] is False


def test_what_to_buy_product_with_quantity_becomes_new_purchase(monkeypatch):
    """무엇을 구매할지 묻는 상태에서 '찌개 두부 하나'는 새 검색 요청이다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="confirm", keywords=["찌개"])),
    )

    result = intent_agent_node(_make_what_to_buy_state("찌개 두부 하나"))

    assert result["intent"] == "buy"
    assert result["keywords"] == ["찌개 두부"]
    assert result["quantity"] == 1
    assert result["needs_clarification"] is False


def test_what_to_buy_payment_confirmation_stays_payment(monkeypatch):
    """무엇을 살지 물은 뒤에도 사용자가 결제를 말하면 기존 장바구니 결제로 간다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="buy", keywords=["결제"])),
    )

    result = intent_agent_node(_make_what_to_buy_state("결제할래"))

    assert result["intent"] == "confirm"
    assert result["keywords"] == []
    assert result["needs_clarification"] is False


def test_product_confirm_replacement_request_searches_new_product(monkeypatch):
    """그거 말고 수박 사줘 → 기존 상품 confirm이 아니라 수박 새 검색."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="next", keywords=["토마토"])),
    )

    state = _make_state("그거 말고 수박 사줘")
    state["pending_action"] = {"type": "product_confirm"}
    result = intent_agent_node(state)

    assert result["intent"] == "buy"
    assert result["keywords"] == ["수박"]
    assert result["quantity"] is None


def test_product_confirm_ack_purchase_does_not_buy_acknowledgement(monkeypatch):
    """응 구매해줘 → 응을 새 상품명으로 추출하지 않고 기존 추천을 확인한다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="buy", keywords=["응"])),
    )

    state = _make_state("응 구매해줘")
    state["pending_action"] = {"type": "product_confirm"}
    result = intent_agent_node(state)

    assert result["intent"] == "confirm"
    assert result["keywords"] == ["토마토"]
    assert result["needs_clarification"] is False


def test_ack_prefixed_product_request_keeps_real_product(monkeypatch):
    """응 수박 구매해줘 → 맞장구는 버리고 실제 상품명 수박으로 새 검색한다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="confirm", keywords=[])),
    )

    state = _make_state("응 수박 구매해줘")
    state["pending_action"] = {"type": "product_confirm"}
    result = intent_agent_node(state)

    assert result["intent"] == "buy"
    assert result["keywords"] == ["수박"]


def test_payment_method_ambiguous_text_is_not_confirm(monkeypatch):
    """payment_method_confirm에서 '음'은 결제 동의로 처리하지 않는다."""
    monkeypatch.setattr(
        intent_agent,
        "_get_llm",
        lambda: _FakeStructuredLlm(IntentOutput(intent="confirm", keywords=[])),
    )

    state = _make_state("음")
    state["pending_action"] = {"type": "payment_method_confirm"}
    result = intent_agent_node(state)

    assert result["intent"] == "unclear"
    assert result["needs_clarification"] is True
