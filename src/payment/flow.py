"""
Payment Flow — MVP.

- 옵션 없음
- 로그인/배송지 기저장 (확인 생략)
- 실제 결제 없음: 주문 DB 저장 후 성공 반환
"""
from typing import Any, Optional
from src.state.schema import PaymentState
from src.tools.mock_tools import (
    get_checkout_session,
    create_checkout_session,
    find_order_by_idempotency_key,
    create_order_from_checkout,
    create_order_item,
    create_payment_record,
    MockValidation,
    transaction,
)


def fail_payment(
    payment: PaymentState,
    payment_stage: str,
    payment_error: str,
    message: str,
    checkout_session_id: Optional[str] = None,
    order_id: Optional[str] = None,
) -> PaymentState:
    return {
        **payment,
        "payment_stage": payment_stage,
        "payment_status": "failed",
        "payment_error": payment_error,
        "checkout_session_id": checkout_session_id or payment.get("checkout_session_id"),
        "order_id": order_id or payment.get("order_id"),
        "pending_action": {
            "type": "payment_confirm",
            "message": message,
            "payload": {},
        },
    }


def payment_flow(payment: PaymentState) -> PaymentState:
    selected_product = payment.get("selected_product") or {}
    user_id = payment.get("user_id")
    conversation_id = payment.get("conversation_id")
    quantity = payment.get("quantity") or 1
    product_url = payment.get("product_url")
    checkout_session_id = payment.get("checkout_session_id")
    payment_retry = payment.get("payment_retry", 0)

    # ═══════════════════════════════════════
    # 1. 기본 검증
    # ═══════════════════════════════════════

    if payment_retry >= 3:
        return fail_payment(
            payment, "failed", "payment_retry_exceeded", "결제 재시도 횟수를 초과했어요."
        )

    if not selected_product:
        return fail_payment(
            payment, "failed", "missing_product", "선택된 상품이 없어요."
        )

    if not product_url:
        return fail_payment(
            payment, "failed", "missing_product_url", "상품 페이지 주소를 확인할 수 없어요."
        )

    if not user_id:
        return fail_payment(
            payment, "failed", "missing_user", "사용자 정보를 확인할 수 없어요."
        )

    # ═══════════════════════════════════════
    # 2. Checkout Session 생성/조회
    # ═══════════════════════════════════════

    checkout = get_checkout_session(checkout_session_id) if checkout_session_id else None

    if not checkout:
        checkout = create_checkout_session(
            user_id=user_id,
            conversation_id=conversation_id,
            product=selected_product,
            product_url=product_url,
            quantity=quantity,
            selected_platform=payment.get("selected_platform"),
        )

    # ═══════════════════════════════════════
    # 3. 중복 주문 방지
    # ═══════════════════════════════════════

    existing_order = find_order_by_idempotency_key(checkout.id)

    if existing_order:
        return {
            **payment,
            "payment_stage": "success",
            "payment_status": "success",
            "payment_error": None,
            "order_id": existing_order.id,
            "checkout_session_id": checkout.id,
            "pending_action": {
                "type": "payment_confirm",
                "message": "이미 완료된 주문입니다.",
                "payload": {"order_id": existing_order.id},
            },
        }

    # ═══════════════════════════════════════
    # 4. 주문 생성 (DB 저장, 실제 결제 없음)
    # ═══════════════════════════════════════

    validation = MockValidation(available=True, price_changed=False)

    with transaction():
        order = create_order_from_checkout(checkout.id, validation)
        create_order_item(order.id, checkout.id, validation)
        create_payment_record(order.id)

    # ═══════════════════════════════════════
    # 5. 성공 반환 (결제 된 척)
    # ═══════════════════════════════════════

    product_name = selected_product.get("product_name", "상품")
    price = selected_product.get("price", 0)

    return {
        **payment,
        "payment_stage": "success",
        "payment_status": "success",
        "payment_error": None,
        "order_id": order.id,
        "checkout_session_id": checkout.id,
        "pending_action": {
            "type": "payment_confirm",
            "message": f"'{product_name}' {quantity}개, {price * quantity:,}원 결제가 완료되었습니다.",
            "payload": {"order_id": order.id},
        },
    }
