"""
cart_shopping 결제 진입 guard 테스트.

selected_product가 비어 있는 상태에서 "0원" 결제 안내가 생성되지 않도록 검증한다.
"""
from src.payment.node import payment_agent_node
from src.state.schema import get_default_shopping_state


def make_state(**overrides) -> dict:
    state = get_default_shopping_state("user_test", "session_test")
    state.update(overrides)
    return state


def test_cart_payment_uses_existing_single_cart_item_when_selected_product_missing():
    """what_to_buy 이후 결제할래 → selected_product가 없어도 기존 cart 기준 결제 안내."""
    state = make_state(
        stage="cart_shopping",
        intent="confirm",
        selected_product=None,
        quantity=1,
        keywords=[],
        cart_items=[
            {
                "product_name": "[제주살림] 제주전통 마른두부 270g",
                "price": 7490,
                "quantity": 1,
                "total": 7490,
                "keywords": ["두부"],
            }
        ],
        pending_action={"type": "what_to_buy"},
    )

    result = payment_agent_node(state)

    assert result["pending_action"]["type"] == "payment_method_confirm"
    assert "두부 1개" in result["pending_action"]["message"]
    assert "총 0원" not in result["pending_action"]["message"]


def test_cart_payment_without_product_or_cart_does_not_create_zero_won_precheck():
    """상품도 장바구니도 없으면 payment_precheck 대신 상품 질문으로 되돌린다."""
    state = make_state(
        stage="cart_shopping",
        intent="confirm",
        selected_product=None,
        quantity=1,
        keywords=["찌개 두부"],
        cart_items=[],
        pending_action={"type": "what_to_buy"},
    )

    result = payment_agent_node(state)

    assert result["stage"] == "cart_shopping"
    assert result["pending_action"]["type"] == "what_to_buy"
    assert "총 0원" not in result["pending_action"]["message"]


def test_payment_method_confirm_requires_default_address():
    """기본 배송지가 없으면 빈 주소 확인 문장을 만들지 않는다."""
    state = make_state(
        stage="payment_processing",
        intent="confirm",
        selected_product={"product_name": "두부", "price": 3000},
        quantity=1,
        pending_action={"type": "payment_method_confirm"},
    )

    result = payment_agent_node(state)

    assert result["pending_action"]["type"] == "address_required"
    assert result["error"] == "address_required"
    assert "로 보낼게요" not in result["pending_action"]["message"]
