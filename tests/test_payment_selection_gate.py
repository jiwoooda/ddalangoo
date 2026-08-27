"""WON-22 Unit 9 — payment_agent Step 0(장바구니 담기) 쪽 최종 검증 게이트.
product_agent의 게이트(tests/test_selection_validation_gate.py)와 같은
원칙을 결제 진입 직전에도 독립적으로 적용한다(완료 조건: "Payment Agent까지
잘못된 제품이 전달되지 않음")."""
import os

os.environ.setdefault("DB_MODE", "mock")

from src.state.schema import get_default_shopping_state
from src.payment.node import payment_agent_node
from src.tools.mock_tools import mock_get_cart, mock_clear_cart


def _state(**kwargs):
    s = get_default_shopping_state("gate_test_user", "gate_test_sess")
    s.update(kwargs)
    return s


def test_wrong_brand_selected_product_is_blocked_before_cart_add():
    mock_clear_cart("gate_test_user")
    state = _state(
        stage="product_confirming",
        intent="confirm",
        pending_action={"type": "product_confirm", "message": "..."},
        selected_product={"product_name": "남양 맛있는우유 1L", "product_url": "https://a", "price": 2600},
        keywords=["서울우유"],
        quantity=1,
        product_request={"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
    )
    result = payment_agent_node(state)

    assert result["error"] == "selection_validation_failed"
    assert result["selected_product"] is None
    # 실제로 장바구니에 안 들어갔는지까지 확인(게이트가 진짜 담기를 막았는지)
    assert mock_get_cart("gate_test_user") == []


def test_matching_product_still_gets_added_to_cart():
    mock_clear_cart("gate_test_user2")
    state = _state(
        user_id="gate_test_user2",
        stage="product_confirming",
        intent="confirm",
        pending_action={"type": "product_confirm", "message": "..."},
        selected_product={"product_name": "서울우유 1L", "product_url": "https://a", "price": 2800},
        keywords=["서울우유"],
        quantity=1,
        product_request={"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
    )
    result = payment_agent_node(state)

    assert result["error"] is None
    assert result["stage"] == "cart_shopping"
    assert len(mock_get_cart("gate_test_user2")) == 1
