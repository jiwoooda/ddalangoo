"""
Router unit tests.
LLM 없이 route() 함수 로직만 검증.
"""
import pytest
from src.graph.router import route, after_respond
from src.state.schema import get_default_shopping_state


def make_state(**overrides) -> dict:
    state = get_default_shopping_state("user_test", "session_test")
    state.update(overrides)
    return state


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
