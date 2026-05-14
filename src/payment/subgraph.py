"""
Payment Agent Node (Main Graph 진입점).

역할:
- bridge_shopping_to_payment()로 PaymentState 생성
- ShoppingState의 현재 intent/슬롯으로 PaymentState 보완 (옵션, 주소, checkout 연속성)
- payment_flow() 실행
- bridge_payment_to_shopping()으로 결과만 ShoppingState에 반영

옵션/주소/checkout/playwright/retry는 PaymentState 내부에서만 관리한다.
"""
from typing import Any, Optional
from src.state.schema import ShoppingState, bridge_shopping_to_payment, bridge_payment_to_shopping
from src.payment.flow import payment_flow
from src.tools.mock_tools import mock_get_default_address


def _resolve_delivery_address(state: ShoppingState) -> Optional[dict[str, Any]]:
    """
    배송지 결정 순서:
    1. address_text가 있으면 간단히 파싱하여 사용
    2. 없으면 None (payment_flow에서 기본 주소 조회 또는 요청)
    """
    address_text = state.get("address_text")
    if address_text:
        return {
            "address_line1": address_text,
            "address_line2": "",
            "recipient_name": "고객",
            "recipient_phone": "",
            "zip_code": "",
        }
    return None


def _resolve_selected_options(
    state: ShoppingState,
    pending_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    사용자가 선택한 옵션을 selected_options 딕셔너리로 조립.
    current_option_value + pending_action.payload.current_option_key 기반.
    """
    option_value = state.get("current_option_value")
    if not option_value:
        return {}

    option_key = pending_payload.get("current_option_key")
    if not option_key:
        # available_options에서 첫 번째 key 추출 시도
        available = pending_payload.get("available_options") or []
        if available:
            option_key = available[0].get("key")

    if option_key:
        return {option_key: option_value}
    return {}


def payment_agent_node(state: ShoppingState) -> dict:
    """
    Payment Subgraph 진입 노드.

    ShoppingState → PaymentState (bridge) → payment_flow() → ShoppingState (bridge)
    옵션/주소/checkout_session_id 연속성은 pending_action.payload에서 복원한다.
    """
    intent = state.get("intent")
    pending_action = state.get("pending_action") or {}
    pending_payload = pending_action.get("payload") or {}
    pending_type = pending_action.get("type")

    # ── 배송지 결정 ──
    delivery_address = _resolve_delivery_address(state)

    # ── 주소 확인 여부 ──
    address_confirmed = False
    if pending_type == "address_confirm" and intent == "confirm":
        # 사용자가 주소를 확인했음
        delivery_address = pending_payload.get("delivery_address") or delivery_address
        address_confirmed = True
    elif pending_type == "address_confirm" and intent == "address_change":
        # 사용자가 새 주소를 입력했음 (address_text에서 resolve)
        address_confirmed = False  # 새 주소는 다시 확인 필요

    # ── 주소가 없으면 기본 배송지 사용 ──
    if not delivery_address:
        delivery_address = mock_get_default_address(state.get("user_id", ""))

    # ── PaymentState 생성 ──
    payment_state = bridge_shopping_to_payment(state, delivery_address)

    # ── Checkout session 연속성 복원 ──
    if pending_payload.get("checkout_session_id"):
        payment_state["checkout_session_id"] = pending_payload["checkout_session_id"]

    # ── Playwright session 연속성 복원 ──
    if pending_payload.get("playwright_session"):
        payment_state["playwright_session"] = pending_payload["playwright_session"]

    # ── 옵션 조립 ──
    selected_options = _resolve_selected_options(state, pending_payload)
    if selected_options:
        payment_state["selected_options"] = selected_options

    # ── available_options 복원 ──
    if pending_payload.get("available_options"):
        payment_state["available_options"] = pending_payload["available_options"]

    # ── 주소 확인 상태 적용 ──
    payment_state["address_confirmed"] = address_confirmed
    if address_confirmed and delivery_address:
        payment_state["delivery_address"] = delivery_address

    # ── payment_flow 실행 ──
    result_state = payment_flow(payment_state)

    # ── ShoppingState로 bridge ──
    return bridge_payment_to_shopping(result_state)
