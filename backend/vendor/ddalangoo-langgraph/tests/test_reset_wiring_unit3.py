"""WON-37 Unit 3 — 장바구니를 '유지'하는 두 지점(_recover_result,
ask_what_to_buy_node)이 Unit 1 카테고리 함수를 쓰도록 배선됐는지 검증.

핵심:
- product_context_reset() + purchase_flow_reset() 조합만 쓴다.
- cart_clear() 는 절대 안 쓴다 → 반환 dict 에 cart_items 키가 없어야 한다
  (= 장바구니는 이 노드가 건드리지 않고 그대로 유지).
- _recover_result 의 corrected_* 교정값은 카테고리 기본값 위에 덮어써야 한다.
"""
from src.state.schema import (
    product_context_reset,
    purchase_flow_reset,
    get_default_shopping_state,
)
from src.agents.nodes import ask_what_to_buy_node
from src.agents.fallback_orchestrator import _recover_result, FallbackDecision

_NEWLY_FOUND = {
    "product_request", "search_query", "exclude_keywords", "negative_constraints",
    "override_platform", "target_platforms", "tried_platforms", "selected_platform",
    "queue_items", "current_queue_index", "queue_source", "queue_clear_existing",
    "recipe_dish", "recipe_people", "cart_operations", "recommendation_context",
}
_CATEGORY_KEYS = set(product_context_reset()) | set(purchase_flow_reset())
_DEFAULT = get_default_shopping_state("u", "s")


# ── ask_what_to_buy_node ───────────────────────────────────────────────

def test_ask_what_to_buy_resets_category_fields():
    result = ask_what_to_buy_node({})
    for k in _CATEGORY_KEYS:
        if k in ("pending_action",):  # 노드 고유값으로 덮어씀
            continue
        assert result[k] == _DEFAULT[k], f"{k}: {result.get(k)!r} != default {_DEFAULT[k]!r}"


def test_ask_what_to_buy_newly_found_fields_reset():
    result = ask_what_to_buy_node({})
    for k in _NEWLY_FOUND:
        assert k in result and result[k] == _DEFAULT[k], f"신규 필드 {k} 미초기화: {result.get(k)!r}"


def test_ask_what_to_buy_does_not_touch_cart():
    result = ask_what_to_buy_node({})
    assert "cart_items" not in result, "장바구니는 이 노드가 건드리면 안 된다"


def test_ask_what_to_buy_keeps_node_specific_values():
    result = ask_what_to_buy_node({})
    assert result["stage"] == "cart_shopping"
    assert result["error"] is None
    assert result["pending_action"]["type"] == "what_to_buy"
    assert result["pending_action"]["message"] == "무엇을 구매하실까요?"


# ── _recover_result ───────────────────────────────────────────────────

def test_recover_result_reset_clears_category_but_not_cart():
    d = FallbackDecision(action="recover", reset_product_context=True)
    result = _recover_result(d)
    assert "cart_items" not in result, "goal-shift 여도 장바구니는 유지"
    for k in _NEWLY_FOUND:
        assert k in result and result[k] == _DEFAULT[k], f"신규 필드 {k} 미초기화: {result.get(k)!r}"
    # 항상 세팅되는 복구 신호
    assert result["needs_clarification"] is False
    assert result["confidence"] == 0.9
    assert result["last_agent"] == "fallback_orchestrator"
    assert result["fallback_stuck_turns"] == 0


def test_recover_result_corrected_values_override_category_defaults():
    d = FallbackDecision(
        action="recover", reset_product_context=True,
        corrected_intent="buy", corrected_keywords=["우유"],
        corrected_quantity=2, corrected_condition="최저가",
        corrected_exclude_keywords=["서울우유"],
    )
    result = _recover_result(d)
    # 카테고리 함수는 keywords=[]/quantity=None/... 로 초기화하지만, 교정값이 이긴다
    assert result["intent"] == "buy"
    assert result["keywords"] == ["우유"]
    assert result["quantity"] == 2
    assert result["condition"] == "최저가"
    assert result["exclude_keywords"] == ["서울우유"]
    # 교정 안 된 나머지는 여전히 초기화
    assert result["queue_items"] == []
    assert result["recipe_dish"] is None
    assert result["selected_product"] is None
    assert result["product_request"] is None


def test_recover_result_without_reset_does_not_clear_context():
    """reset_product_context=False 면 카테고리 초기화를 안 한다(회귀 가드)."""
    d = FallbackDecision(action="recover", reset_product_context=False,
                         corrected_intent="ask")
    result = _recover_result(d)
    assert "queue_items" not in result
    assert "search_results" not in result
    assert "product_request" not in result
    assert result["intent"] == "ask"
