"""
Router unit tests.
LLM 없이 route() 함수 로직만 검증.
"""
import pytest
import langgraph.errors

if not hasattr(langgraph.errors, "NodeError"):
    class NodeError(Exception):
        pass

    langgraph.errors.NodeError = NodeError

from src.graph.router import route, route_session_start, after_respond
from src.state.schema import get_default_shopping_state


def make_state(**overrides) -> dict:
    state = get_default_shopping_state("user_test", "session_test")
    state.update(overrides)
    return state


def test_session_start_new_user_greets_first(monkeypatch):
    from src.tools import db_client

    monkeypatch.setattr(db_client, "get_profile", lambda user_id: None)
    monkeypatch.setattr(db_client, "get_purchase_histories", lambda user_id: [])
    assert route_session_start(make_state(messages=[])) == "smalltalk_agent"


def test_session_start_onboarded_user_waits(monkeypatch):
    from src.tools import db_client

    monkeypatch.setattr(db_client, "get_profile", lambda user_id: {"onboarded_at": "now"})
    monkeypatch.setattr(db_client, "get_purchase_histories", lambda user_id: [])
    assert route_session_start(make_state(messages=[])) == "wait_for_input"


def test_session_start_with_existing_message_does_not_preempt_input(monkeypatch):
    assert route_session_start(
        make_state(messages=[{"role": "user", "content": "우유 사줘"}])
    ) == "wait_for_input"


def test_graph_new_session_emits_assistant_greeting_before_wait(monkeypatch):
    from src.tools import db_client
    import src.graph.builder as graph_builder

    monkeypatch.setattr(db_client, "get_profile", lambda user_id: None)
    monkeypatch.setattr(db_client, "get_purchase_histories", lambda user_id: [])

    def fake_smalltalk(state, runtime=None):
        greeting = "안녕하세요, 쇼핑을 도와드릴 딸랑구예요. 성함이 어떻게 되세요?"
        return {
            "explanation": greeting,
            "immediate_response": greeting,
            "pending_action": None,
            "onboarding_started_at": "now",
            "stage": "idle",
            "last_agent": "smalltalk_agent",
            "error": None,
        }

    monkeypatch.setattr(graph_builder, "smalltalk_agent_node", fake_smalltalk)
    graph = graph_builder.build_graph()
    config = {"configurable": {"thread_id": "proactive-greeting-test"}}
    graph.invoke(make_state(messages=[]), config)

    current = graph.get_state(config)
    assert current.next == ("wait_for_input",)
    last_message = current.values["messages"][-1]
    assert getattr(last_message, "type", None) == "ai"
    assert "성함이 어떻게 되세요?" in last_message.content


# ══════════════════════════════════════════════
# Clarification 우선
# ══════════════════════════════════════════════

def test_route_needs_clarification():
    state = make_state(intent="buy", confidence=0.9, needs_clarification=True)
    assert route(state) == "respond"


def test_route_low_confidence():
    state = make_state(intent="buy", confidence=0.3, needs_clarification=False)
    assert route(state) == "respond"


def test_route_unclear_intent():
    state = make_state(intent="unclear", confidence=0.8, needs_clarification=False)
    assert route(state) == "respond"


# ══════════════════════════════════════════════
# Cancel 우선
# ══════════════════════════════════════════════

def test_route_cancel_idle():
    state = make_state(intent="cancel", stage="idle", confidence=0.9, needs_clarification=False)
    assert route(state) == "cancel"


def test_route_cancel_payment_processing():
    state = make_state(
        intent="cancel",
        stage="payment_processing",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "cancel"


# ══════════════════════════════════════════════
# Payment processing stage
# ══════════════════════════════════════════════

def test_route_payment_processing_confirm():
    state = make_state(
        intent="confirm",
        stage="payment_processing",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "payment_agent"


def test_route_payment_processing_option_select():
    state = make_state(
        intent="option_select",
        stage="payment_processing",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "payment_agent"


def test_route_payment_processing_address_change():
    state = make_state(
        intent="address_change",
        stage="payment_processing",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "payment_agent"


# ══════════════════════════════════════════════
# Cart shopping stage — 결제/추가 쇼핑 분기
# ══════════════════════════════════════════════

def test_route_cart_shopping_confirm_goes_to_payment():
    """장바구니 다음 질문에 순수 확인이면 결제 단계로 간다."""
    state = make_state(
        intent="confirm",
        stage="cart_shopping",
        confidence=0.9,
        needs_clarification=False,
        keywords=[],
        pending_action={"type": "continue_shopping"},
    )
    assert route(state) == "payment_agent"


def test_route_cart_shopping_buy_goes_to_platform_search():
    """새 상품 추가 의도는 기존 상품 결제가 아니라 검색 흐름으로 돌아가야 한다."""
    state = make_state(
        intent="buy",
        stage="cart_shopping",
        confidence=0.9,
        needs_clarification=False,
        keywords=["오이"],
        pending_action={"type": "continue_shopping"},
    )
    assert route(state) == "platform_agent"


def test_route_cart_shopping_confirm_with_keyword_goes_to_platform_search():
    """LLM이 confirm으로 오판해도 키워드가 있으면 이전 selected_product 결제를 막는다."""
    state = make_state(
        intent="confirm",
        stage="cart_shopping",
        confidence=0.9,
        needs_clarification=False,
        keywords=["오이"],
        pending_action={"type": "continue_shopping"},
    )
    assert route(state) == "platform_agent"


def test_route_cart_shopping_what_to_buy_confirm_with_keyword_searches():
    """what_to_buy 상태에서 상품 키워드가 있으면 confirm 오판이어도 결제로 가지 않는다."""
    state = make_state(
        intent="confirm",
        stage="cart_shopping",
        confidence=0.9,
        needs_clarification=False,
        keywords=["찌개 두부"],
        pending_action={"type": "what_to_buy"},
    )
    assert route(state) == "platform_agent"


def test_route_cart_shopping_what_to_buy_confirm_without_keyword_pays_cart():
    """what_to_buy 상태라도 사용자가 결제를 명시하면 기존 장바구니 결제로 간다."""
    state = make_state(
        intent="confirm",
        stage="cart_shopping",
        confidence=0.9,
        needs_clarification=False,
        keywords=[],
        pending_action={"type": "what_to_buy"},
    )
    assert route(state) == "payment_agent"


# ══════════════════════════════════════════════
# Product confirming stage
# ══════════════════════════════════════════════

def test_route_product_confirming_confirm():
    state = make_state(
        intent="confirm",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
        quantity=1,
    )
    assert route(state) == "payment_agent"


def test_route_product_confirming_next():
    state = make_state(
        intent="next",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "product_agent"


def test_route_product_confirming_deny():
    state = make_state(
        intent="deny",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "product_agent"


def test_route_product_confirming_ask():
    state = make_state(
        intent="ask",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "product_agent"


def test_route_product_confirming_refine():
    state = make_state(
        intent="refine",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "platform_agent"


def test_route_product_confirming_compare_platforms():
    state = make_state(
        intent="compare_platforms",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
    )
    assert route(state) == "platform_agent"


def test_route_product_confirming_new_buy_replaces_current_product():
    """상품 확인 중 새 상품 구매 요청이 오면 기존 추천 반복이 아니라 새 검색으로 간다."""
    state = make_state(
        intent="buy",
        stage="product_confirming",
        confidence=0.9,
        needs_clarification=False,
        keywords=["수박"],
        pending_action={"type": "product_confirm"},
    )
    assert route(state) == "platform_agent"


# ══════════════════════════════════════════════
# Idle stage — routing map
# ══════════════════════════════════════════════

def test_route_idle_buy():
    state = make_state(intent="buy", stage="idle", confidence=0.9, needs_clarification=False)
    assert route(state) == "memory_agent"


def test_route_idle_reorder():
    state = make_state(intent="reorder", stage="idle", confidence=0.9, needs_clarification=False)
    assert route(state) == "memory_agent"


def test_route_idle_compare_platforms():
    state = make_state(intent="compare_platforms", stage="idle", confidence=0.9, needs_clarification=False)
    assert route(state) == "platform_agent"


def test_route_idle_ask():
    state = make_state(intent="ask", stage="idle", confidence=0.9, needs_clarification=False)
    assert route(state) == "product_agent"


def test_route_idle_confirm_no_pending():
    state = make_state(intent="confirm", stage="idle", confidence=0.9, needs_clarification=False)
    assert route(state) == "respond"


# ══════════════════════════════════════════════
# after_respond
# ══════════════════════════════════════════════

def test_after_respond_completed():
    state = make_state(stage="completed")
    assert after_respond(state) == "end"


def test_after_respond_failed():
    state = make_state(stage="failed")
    assert after_respond(state) == "end"


def test_after_respond_fatal_error():
    state = make_state(stage="idle", error="FATAL: something went wrong")
    assert after_respond(state) == "end"


def test_after_respond_continue():
    state = make_state(stage="idle", error=None)
    assert after_respond(state) == "wait_for_input"


def test_after_respond_product_confirming():
    state = make_state(stage="product_confirming")
    assert after_respond(state) == "wait_for_input"


def test_after_respond_payment_processing():
    state = make_state(stage="payment_processing")
    assert after_respond(state) == "wait_for_input"
