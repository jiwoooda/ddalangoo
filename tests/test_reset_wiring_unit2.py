"""WON-37 Unit 2 — 장바구니 삭제 동반 두 지점(cancel_node, 결제완료)이
Unit 1 카테고리 함수를 쓰도록 배선됐는지 검증.

핵심: 새로 발견된 12개 필드가 이 두 지점에서 실제로 초기화되는가 +
노드 고유값(stage / pending_action 메시지 등)은 그대로 위에 얹혔는가 +
장바구니는 실제로 비워지는가.
"""
import pytest

from src.state.schema import (
    product_context_reset,
    purchase_flow_reset,
    cart_clear,
    get_default_shopping_state,
)
from src.agents.nodes import cancel_node
from src.payment.node import payment_agent_node
from src.tools.mock_tools import mock_clear_cart, mock_add_to_cart, mock_get_purchase_history

_NEWLY_FOUND = {
    "product_request", "search_query", "exclude_keywords", "negative_constraints",
    "override_platform", "target_platforms", "tried_platforms", "selected_platform",
    "queue_items", "current_queue_index", "queue_source", "queue_clear_existing",
    "recipe_dish", "recipe_people", "cart_operations", "recommendation_context",
}

_CATEGORY_KEYS = set(product_context_reset()) | set(purchase_flow_reset()) | set(cart_clear())


def _dirty(**over):
    s = get_default_shopping_state("u1", "s1")
    s.update({
        "user_id": "u1",
        "keywords": ["우유"], "search_query": "우유", "exclude_keywords": ["서울우유"],
        "negative_constraints": ["무가당"], "quantity": 3, "condition": "최저가",
        "product_request": {"category": "우유"},
        "override_platform": "coupang", "target_platforms": ["coupang", "kurly"],
        "tried_platforms": ["coupang"], "selected_platform": "coupang",
        "search_results": [{"x": 1}], "scored_products": [{"x": 1}],
        "recommended_products": [{"x": 1}], "current_product_index": 2,
        "selected_product": {"product_name": "서울우유 1L", "price": 2800,
                             "platform": "coupang", "product_url": "http://x",
                             "delivery": "로켓배송", "delivery_fee": 0},
        "product_url": "http://x", "explanation": "설명", "highlight_specs": ["1L"],
        "queue_items": [{"name": "계란"}], "current_queue_index": 1,
        "queue_source": "multi_buy", "queue_clear_existing": True,
        "cart_operations": [{"op": "CLEAR_CART"}],
        "recipe_dish": "된장찌개", "recipe_people": 4,
        "recommendation_context": {"x": 1}, "reorder_resolution": {"x": 1},
        "payment_idempotency_key": "key-123",
        "pending_action": {"type": "cart_review", "message": "..."},
        "cart_items": [{"product_name": "서울우유 1L", "price": 2800, "quantity": 3, "total": 8400}],
    })
    s.update(over)
    return s


# ── cancel_node ────────────────────────────────────────────────────────

def test_cancel_node_resets_every_category_field_to_default():
    default = get_default_shopping_state("u1", "s1")
    result = cancel_node(_dirty())
    for k in _CATEGORY_KEYS:
        if k == "pending_action":  # cancel 고유값으로 덮어씀
            continue
        assert result[k] == default[k], f"{k}: {result.get(k)!r} != default {default[k]!r}"


def test_cancel_node_newly_found_fields_reset():
    default = get_default_shopping_state("u1", "s1")
    result = cancel_node(_dirty())
    for k in _NEWLY_FOUND:
        assert k in result and result[k] == default[k], f"신규 필드 {k} 미초기화: {result.get(k)!r}"


def test_cancel_node_keeps_node_specific_values():
    result = cancel_node(_dirty())
    assert result["stage"] == "idle"
    assert result["intent"] is None
    assert result["error"] is None
    assert result["last_agent"] == "cancel"
    assert result["pending_action"]["type"] == "payment_confirm"
    assert "장바구니를 모두 비웠어요" in result["pending_action"]["message"]
    assert result["cart_items"] == []


def test_cancel_node_calls_mock_clear_cart(monkeypatch):
    calls = []
    monkeypatch.setattr("src.agents.nodes.mock_clear_cart", lambda uid: calls.append(uid))
    cancel_node(_dirty(user_id="u77"))
    assert calls == ["u77"]


# ── 결제완료(payment_agent_node Step 4) ────────────────────────────────

def test_payment_completion_resets_categories_and_clears_cart():
    uid = "won37u2_complete"
    mock_clear_cart(uid)
    mock_add_to_cart(uid, {"product_name": "서울우유 1L", "price": 2800,
                           "platform": "coupang", "product_url": "http://x"}, 1, ["서울우유"])
    default = get_default_shopping_state(uid, "s")

    state = _dirty(
        user_id=uid,
        stage="payment_processing",
        intent="confirm",
        pending_action={"type": "payment_password", "message": "비밀번호"},
        address_text="서울시 강남구 테헤란로 1",
        payment_idempotency_key="won37u2-key",
    )
    result = payment_agent_node(state)

    assert result["stage"] == "completed"
    assert result.get("order_id")
    assert result["cart_items"] == []
    assert mock_get_purchase_history(uid), "구매이력이 저장돼야 한다"

    # 신규 발견 필드 + 카테고리 필드가 완료 출력에서 초기화됐는가
    for k in _NEWLY_FOUND:
        assert k in result and result[k] == default[k], f"결제완료: 신규 필드 {k} 미초기화 {result.get(k)!r}"
    for k in (set(product_context_reset()) | set(purchase_flow_reset())):
        if k in ("pending_action",):
            continue
        assert result[k] == default[k], f"결제완료: {k} 미초기화 {result.get(k)!r}"

    # 노드 고유값
    assert result["pending_action"]["type"] == "payment_confirm"
    assert result["payment_idempotency_key"] is None
    assert result["last_agent"] == "payment_agent"
