"""
Payment flow unit tests.
LLM 없이 payment_flow() 함수 로직만 검증.
"""
import pytest
from src.state.schema import PaymentState, bridge_shopping_to_payment, bridge_payment_to_shopping, get_default_shopping_state
from src.payment.flow import payment_flow, fail_payment, wait_for_user_action


MOCK_PRODUCT = {
    "product_name": "설향 딸기 500g",
    "price": 12900,
    "platform": "kurly",
    "product_url": "https://mock.kurly.com/products/strawberry-500g",
    "is_sold_out": False,
}


def make_payment_state(**overrides) -> PaymentState:
    base: PaymentState = {
        "user_id": "user_test",
        "conversation_id": None,
        "selected_product": MOCK_PRODUCT,
        "product_url": MOCK_PRODUCT["product_url"],
        "quantity": 1,
        "selected_platform": "kurly",
        "available_options": [],
        "current_option_index": 0,
        "current_option_key": None,
        "current_option_value": None,
        "selected_options": {},
        "delivery_address": None,
        "address_confirmed": False,
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
    base.update(overrides)
    return base


# ══════════════════════════════════════════════
# Validation tests
# ══════════════════════════════════════════════

def test_payment_flow_missing_product():
    state = make_payment_state(selected_product={})
    result = payment_flow(state)
    assert result["payment_status"] == "failed"
    assert result["payment_error"] == "missing_product"


def test_payment_flow_missing_product_url():
    state = make_payment_state(product_url="")
    result = payment_flow(state)
    assert result["payment_status"] == "failed"
    assert result["payment_error"] == "missing_product_url"


def test_payment_flow_missing_user():
    state = make_payment_state(user_id="")
    result = payment_flow(state)
    assert result["payment_status"] == "failed"
    assert result["payment_error"] == "missing_user"


def test_payment_flow_retry_exceeded():
    state = make_payment_state(payment_retry=3)
    result = payment_flow(state)
    assert result["payment_status"] == "failed"
    assert result["payment_error"] == "payment_retry_exceeded"


# ══════════════════════════════════════════════
# 옵션 선택 대기 (딸기 - 용량 옵션 있음)
# ══════════════════════════════════════════════

def test_payment_flow_option_required():
    """옵션이 있는 상품 → option_select pending_action 반환."""
    state = make_payment_state()
    result = payment_flow(state)

    assert result["payment_stage"] == "option_selecting"
    assert result["payment_status"] == "pending_user_action"
    assert result["pending_action"] is not None
    assert result["pending_action"]["type"] == "option_select"
    assert "available_options" in result["pending_action"]["payload"]


def test_payment_flow_with_option_selected():
    """옵션 선택 후 → 주소 확인 단계로 진행."""
    state = make_payment_state(
        selected_options={"용량": "500g"},
        available_options=[{"key": "용량", "values": ["500g", "1kg"]}],
    )
    result = payment_flow(state)

    # 옵션 적용 성공 → 주소 단계
    assert result["payment_stage"] == "address_confirming"
    assert result["pending_action"]["type"] == "address_confirm"


def test_payment_flow_address_required():
    """배송지 없음 → address_confirm pending_action 반환."""
    state = make_payment_state(
        selected_options={"용량": "500g"},
        available_options=[{"key": "용량", "values": ["500g", "1kg"]}],
        delivery_address=None,
    )
    result = payment_flow(state)
    assert result["payment_stage"] == "address_confirming"
    assert result["pending_action"]["type"] == "address_confirm"


def test_payment_flow_address_confirm_required():
    """배송지 있지만 미확인 → confirm 요청."""
    state = make_payment_state(
        selected_options={"용량": "500g"},
        available_options=[{"key": "용량", "values": ["500g", "1kg"]}],
        delivery_address={
            "address_line1": "서울 강남구 테헤란로 123",
            "recipient_name": "김영희",
        },
        address_confirmed=False,
    )
    result = payment_flow(state)
    assert result["payment_stage"] == "address_confirming"
    assert result["pending_action"]["type"] == "address_confirm"


def test_payment_flow_full_success():
    """
    전체 플로우 성공 경로:
    - 옵션 없는 상품 (사과 등 단순 상품)
    - 배송지 확인됨
    → payment_password_required 대기
    """
    # mock: 사과 URL → extract_available_options → 옵션 없음
    state = make_payment_state(
        selected_product={
            "product_name": "사과 1kg",
            "price": 9900,
            "platform": "naver",
            "product_url": "https://mock.naver.com/apple",
        },
        product_url="https://mock.naver.com/apple",
        selected_options={},
        available_options=[],  # 옵션 없음
        delivery_address={
            "address_line1": "서울 강남구 테헤란로 123",
            "address_line2": "101호",
            "recipient_name": "테스트유저",
            "recipient_phone": "010-0000-0000",
            "zip_code": "06234",
        },
        address_confirmed=True,
    )
    result = payment_flow(state)

    assert result["payment_stage"] == "payment_password_required"
    assert result["payment_status"] == "pending_user_action"
    assert result["pending_action"]["type"] == "payment_confirm"
    assert result["checkout_session_id"] is not None
    assert result["order_id"] is not None


# ══════════════════════════════════════════════
# Bridge function tests
# ══════════════════════════════════════════════

def test_bridge_shopping_to_payment():
    shopping_state = get_default_shopping_state("user_test", "session_test")
    shopping_state["selected_product"] = MOCK_PRODUCT
    shopping_state["product_url"] = MOCK_PRODUCT["product_url"]
    shopping_state["quantity"] = 2
    shopping_state["selected_platform"] = "kurly"

    payment_state = bridge_shopping_to_payment(shopping_state)

    assert payment_state["user_id"] == "user_test"
    assert payment_state["selected_product"] == MOCK_PRODUCT
    assert payment_state["product_url"] == MOCK_PRODUCT["product_url"]
    assert payment_state["quantity"] == 2
    assert payment_state["payment_stage"] == "validate_input"
    assert payment_state["payment_status"] == "pending"
    assert payment_state["selected_options"] == {}


def test_bridge_payment_to_shopping_success():
    payment_state = make_payment_state(
        payment_status="success",
        payment_error=None,
    )
    result = bridge_payment_to_shopping(payment_state)
    assert result["stage"] == "completed"
    assert result["error"] is None
    assert result["last_agent"] == "payment_agent"


def test_bridge_payment_to_shopping_failed():
    payment_state = make_payment_state(
        payment_status="failed",
        payment_error="cart_failed",
    )
    result = bridge_payment_to_shopping(payment_state)
    assert result["stage"] == "failed"
    assert result["error"] == "cart_failed"
    assert result["last_agent"] == "payment_agent"


def test_bridge_payment_to_shopping_pending_user_action():
    pending_action = {
        "type": "option_select",
        "message": "용량을 선택해 주세요.",
        "payload": {},
    }
    payment_state = make_payment_state(
        payment_status="pending_user_action",
        payment_error=None,
        pending_action=pending_action,
    )
    result = bridge_payment_to_shopping(payment_state)
    assert result["stage"] == "payment_processing"
    assert result["pending_action"] == pending_action
    assert result["last_agent"] == "payment_agent"


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def test_fail_payment_helper():
    state = make_payment_state()
    result = fail_payment(state, "failed", "test_error", "테스트 오류")
    assert result["payment_status"] == "failed"
    assert result["payment_error"] == "test_error"
    assert result["pending_action"]["message"] == "테스트 오류"


def test_wait_for_user_action_helper():
    state = make_payment_state()
    result = wait_for_user_action(
        state,
        payment_stage="option_selecting",
        message="옵션 선택해 주세요.",
        pending_action={"type": "option_select", "message": "옵션 선택해 주세요.", "payload": {}},
    )
    assert result["payment_stage"] == "option_selecting"
    assert result["payment_status"] == "pending_user_action"
    assert result["pending_action"]["type"] == "option_select"
