"""
Payment Flow.

역할: PaymentState lifecycle 관리.
- 옵션 선택, 장바구니, 주소 확인, 가격 재검증, 주문 생성, 결제창 진입.

주의:
- recommendation/search는 하지 않는다.
- ShoppingState를 직접 수정하지 않는다.
- PaymentState 내부 lifecycle만 관리한다.
"""
from typing import Any, Optional
from src.state.schema import PaymentState
from src.tools.mock_tools import (
    get_checkout_session,
    create_checkout_session,
    get_or_create_playwright_session,
    extract_available_options,
    build_option_question,
    apply_options_to_page,
    add_to_cart_or_buy_now,
    fill_delivery_address,
    format_address_confirm_message,
    revalidate_product_on_page,
    update_checkout_price,
    find_order_by_idempotency_key,
    create_order_from_checkout,
    create_order_item,
    create_payment_record,
    mark_order_payment_failed,
    proceed_to_naverpay,
    open_webview,
    transaction,
)

# ══════════════════════════════════════════════
# PaymentState 반환 헬퍼
# ══════════════════════════════════════════════

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


def wait_for_user_action(
    payment: PaymentState,
    payment_stage: str,
    message: str,
    pending_action: dict[str, Any],
    payment_status: str = "pending_user_action",
    payment_error: Optional[str] = None,
    checkout_session_id: Optional[str] = None,
    playwright_session: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    ui_command: Optional[dict[str, Any]] = None,
) -> PaymentState:
    result = {
        **payment,
        "payment_stage": payment_stage,
        "payment_status": payment_status,
        "payment_error": payment_error,
        "pending_action": {
            **pending_action,
            "ui_command": ui_command,
        },
    }
    if checkout_session_id:
        result["checkout_session_id"] = checkout_session_id
    if playwright_session:
        result["playwright_session"] = playwright_session
    if extra:
        result.update(extra)
    return result


# ══════════════════════════════════════════════
# Main Payment Flow
# ══════════════════════════════════════════════

def payment_flow(payment: PaymentState) -> PaymentState:
    """
    Payment Subgraph Main Flow.

    역할:
    - 옵션 선택
    - 장바구니/바로구매
    - 주소 확인 및 입력
    - 가격 재검증
    - 주문 생성
    - 결제창 진입

    주의:
    - recommendation/search는 하지 않는다.
    - ShoppingState를 직접 수정하지 않는다.
    - PaymentState 내부 lifecycle만 관리한다.
    """
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
            payment,
            payment_stage="failed",
            payment_error="payment_retry_exceeded",
            message="결제 재시도 횟수를 초과했어요.",
        )

    if not selected_product:
        return fail_payment(
            payment,
            payment_stage="failed",
            payment_error="missing_product",
            message="선택된 상품이 없어요.",
        )

    if not product_url:
        return fail_payment(
            payment,
            payment_stage="failed",
            payment_error="missing_product_url",
            message="상품 페이지 주소를 확인할 수 없어요.",
        )

    if not user_id:
        return fail_payment(
            payment,
            payment_stage="failed",
            payment_error="missing_user",
            message="사용자 정보를 확인할 수 없어요.",
        )

    # ═══════════════════════════════════════
    # 2. Checkout Session 생성/조회
    # ═══════════════════════════════════════

    checkout = (
        get_checkout_session(checkout_session_id)
        if checkout_session_id
        else None
    )

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
    # 3. Playwright Session 준비
    # ═══════════════════════════════════════

    browser_session = get_or_create_playwright_session(
        user_id=user_id,
        session_key=payment.get("playwright_session"),
    )

    # ═══════════════════════════════════════
    # 4. 상품 페이지 진입
    # ═══════════════════════════════════════

    page_state = browser_session.open_product_page(product_url)

    if page_state.failed:
        return fail_payment(
            payment,
            payment_stage="open_product_page",
            payment_error="product_page_open_failed",
            message="상품 페이지를 열지 못했어요. 다른 상품으로 다시 선택해 주세요.",
            checkout_session_id=checkout.id,
        )

    # ═══════════════════════════════════════
    # 5. 옵션 추출/선택
    # ═══════════════════════════════════════

    available_options = payment.get("available_options") or extract_available_options(page_state.page)
    selected_options = payment.get("selected_options") or {}

    # 옵션이 있는데 아직 선택 안 됨
    if available_options and not selected_options:
        option_message = build_option_question(available_options, current_index=0)

        return wait_for_user_action(
            payment,
            payment_stage="option_selecting",
            message=option_message,
            checkout_session_id=checkout.id,
            playwright_session=browser_session.id,
            extra={
                "available_options": available_options,
                "current_option_index": 0,
                "current_option_key": (
                    available_options[0].get("key") if available_options else None
                ),
            },
            pending_action={
                "type": "option_select",
                "message": option_message,
                "payload": {
                    "available_options": available_options,
                    "checkout_session_id": checkout.id,
                    "current_option_key": (
                        available_options[0].get("key") if available_options else None
                    ),
                },
            },
        )

    # 선택된 옵션 적용
    if selected_options:
        option_result = apply_options_to_page(page_state.page, selected_options)

        if option_result.failed:
            return wait_for_user_action(
                payment,
                payment_stage="option_selecting",
                payment_error="option_apply_failed",
                message="선택하신 옵션을 적용하지 못했어요. 다시 선택해 주세요.",
                checkout_session_id=checkout.id,
                playwright_session=browser_session.id,
                pending_action={
                    "type": "option_select",
                    "message": "옵션을 다시 선택해 주세요.",
                    "payload": {
                        "available_options": available_options,
                        "checkout_session_id": checkout.id,
                    },
                },
            )

    # ═══════════════════════════════════════
    # 6. 장바구니 또는 바로구매
    # ═══════════════════════════════════════

    cart_result = add_to_cart_or_buy_now(page_state.page, quantity=quantity)

    if cart_result.failed:
        return fail_payment(
            payment,
            payment_stage="cart",
            payment_error="cart_failed",
            message="상품을 장바구니에 담지 못했어요.",
            checkout_session_id=checkout.id,
        )

    # ═══════════════════════════════════════
    # 7. 배송지 확인
    # ═══════════════════════════════════════

    delivery_address = payment.get("delivery_address") or checkout.delivery_address

    if not delivery_address:
        return wait_for_user_action(
            payment,
            payment_stage="address_confirming",
            message="배송지를 말씀해 주세요.",
            checkout_session_id=checkout.id,
            pending_action={
                "type": "address_confirm",
                "message": "배송지를 말씀해 주세요.",
                "payload": {
                    "checkout_session_id": checkout.id,
                },
            },
        )

    # 주소 확인 필요
    if not payment.get("address_confirmed", False):
        confirm_message = format_address_confirm_message(delivery_address)

        return wait_for_user_action(
            payment,
            payment_stage="address_confirming",
            message=confirm_message,
            checkout_session_id=checkout.id,
            extra={"delivery_address": delivery_address},
            pending_action={
                "type": "address_confirm",
                "message": confirm_message,
                "payload": {
                    "delivery_address": delivery_address,
                    "checkout_session_id": checkout.id,
                },
            },
        )

    # 실제 페이지에 주소 입력
    address_result = fill_delivery_address(page_state.page, delivery_address)

    if address_result.failed:
        return wait_for_user_action(
            payment,
            payment_stage="address_confirming",
            payment_error="address_fill_failed",
            message="배송지 입력에 문제가 있어요. 주소를 다시 확인해 주세요.",
            checkout_session_id=checkout.id,
            pending_action={
                "type": "address_confirm",
                "message": "배송지를 다시 확인해 주세요.",
                "payload": {"checkout_session_id": checkout.id},
            },
        )

    # ═══════════════════════════════════════
    # 8. 결제 직전 재검증
    # ═══════════════════════════════════════

    validation = revalidate_product_on_page(page_state.page)

    if not validation.available:
        return fail_payment(
            payment,
            payment_stage="payment_precheck",
            payment_error="product_unavailable",
            message="현재 구매할 수 없는 상품이에요.",
            checkout_session_id=checkout.id,
        )

    if validation.price_changed:
        update_checkout_price(checkout.id, validation.current_price)
        changed_message = (
            f"가격이 {validation.current_price:,}원으로 변경됐어요. 계속 진행할까요?"
        )

        return wait_for_user_action(
            payment,
            payment_stage="payment_precheck",
            message=changed_message,
            checkout_session_id=checkout.id,
            pending_action={
                "type": "price_change_confirm",
                "message": changed_message,
                "payload": {
                    "old_price": checkout.price,
                    "new_price": validation.current_price,
                    "checkout_session_id": checkout.id,
                },
            },
        )

    # ═══════════════════════════════════════
    # 9. 중복 주문 방지
    # ═══════════════════════════════════════

    existing_order = find_order_by_idempotency_key(checkout.id)

    if existing_order:
        return wait_for_user_action(
            payment,
            payment_stage="payment_precheck",
            message="이미 진행 중인 주문이 있어요. 결제창을 다시 열게요.",
            checkout_session_id=checkout.id,
            extra={"order_id": existing_order.id},
            pending_action={
                "type": "payment_confirm",
                "message": "이미 진행 중인 주문이 있어요. 결제창을 다시 열게요.",
                "payload": {"checkout_session_id": checkout.id},
            },
            ui_command=open_webview("payment", existing_order.payment_url),
        )

    # ═══════════════════════════════════════
    # 10. 주문 생성
    # ═══════════════════════════════════════

    with transaction():
        order = create_order_from_checkout(checkout.id, validation)
        create_order_item(order.id, checkout.id, validation)
        payment_record = create_payment_record(order.id)

    # ═══════════════════════════════════════
    # 11. 결제창 진입
    # ═══════════════════════════════════════

    payment_page = proceed_to_naverpay(page_state.page)

    if payment_page.failed:
        mark_order_payment_failed(order.id)
        return fail_payment(
            payment,
            payment_stage="processing",
            payment_error="naverpay_open_failed",
            message="결제창을 열지 못했어요.",
            checkout_session_id=checkout.id,
            order_id=order.id,
        )

    # ═══════════════════════════════════════
    # 12. 사용자 인증 대기
    # ═══════════════════════════════════════

    return wait_for_user_action(
        payment,
        payment_stage="payment_password_required",
        payment_status="pending_user_action",
        message="결제창에서 비밀번호나 인증을 완료해 주세요.",
        checkout_session_id=checkout.id,
        playwright_session=browser_session.id,
        extra={"order_id": order.id},
        ui_command=open_webview("payment", payment_page.url),
        pending_action={
            "type": "payment_confirm",
            "message": "결제창에서 비밀번호나 인증을 완료해 주세요.",
            "payload": {
                "checkout_session_id": checkout.id,
                "order_id": order.id,
            },
        },
    )
