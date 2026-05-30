from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import (
    address_repository,
    agent_event_repository,
    conversation_repository,
    order_repository,
    payment_repository,
)
from app.agent import runtime
from app.schemas.payment import PaymentDetailResponse, WebviewResultRequest, PaymentRetryRequest
from app.services import purchase_history_service, webview_progress_service
from fastapi import HTTPException

try:
    from langchain_core.messages import AIMessage
except ImportError:  # pragma: no cover - langchain_core는 앱 런타임 의존성이다.
    AIMessage = None

def _to_detail(p: dict) -> PaymentDetailResponse:
    return PaymentDetailResponse(
        paymentId=p["id"], orderId=p["order_id"], paymentProvider=p.get("payment_provider"),
        paymentMethod=p.get("payment_method"), paymentStatus=p.get("payment_status", ""),
        paymentAmount=p.get("payment_amount", 0), externalPaymentId=p.get("external_payment_id"),
        approvalNumber=p.get("approval_number"), paidAt=_iso(p.get("paid_at")),
        cancelledAt=_iso(p.get("cancelled_at")), failureReason=p.get("failure_reason")
    )


def _iso(value):
    """datetime 값을 API DTO에 맞는 문자열로 변환한다."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


async def get_payment_db(db: AsyncSession, payment_id: int) -> PaymentDetailResponse:
    p = await payment_repository.get_payment_by_id_db(db, payment_id)
    if not p:
        raise HTTPException(status_code=404, detail={"category": "PAYMENT_ERROR", "code": "PAYMENT_NOT_FOUND", "message": "결제를 찾을 수 없습니다."})
    return _to_detail(p)

def handle_webview_result(conversation_id: int, req: WebviewResultRequest):
    conv = conversation_repository.get_conversation_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail={"category": "CONVERSATION_ERROR", "code": "CONVERSATION_NOT_FOUND", "message": "대화를 찾을 수 없습니다."})
    base = {"conversationId": conversation_id, "recommendationId": None, "recommendations": [],
            "selectedProduct": None, "pendingConfirmation": None, "availableOptions": None,
            "deliveryAddress": None, "order": None, "payment": None, "asyncStatus": None}
    if req.result == "completed":
        conv["stage"] = "completed"
        return {**base, "status": "order_completed", "stage": "completed",
                "assistantMessage": "결제가 완료되었습니다.", "uiCommand": {"type": "close_webview"}, "error": None}
    elif req.result == "cancelled":
        conv["stage"] = "cancelled"
        return {**base, "status": "cancelled", "stage": "cancelled",
                "assistantMessage": "결제가 취소되었습니다.", "uiCommand": None, "error": None}
    else:
        conv["stage"] = "failed"
        return {**base, "status": "failed", "stage": "failed",
                "assistantMessage": "결제에 실패했습니다.", "uiCommand": None,
                "error": {"category": "PAYMENT_ERROR", "code": "PAYMENT_FAILED", "message": "결제 실패"}}


def _assistant_message_patch(message: str) -> list:
    """결제 결과 반영 후 checkpoint의 마지막 assistant 메시지를 갱신한다."""
    if AIMessage is None:
        return [{"role": "assistant", "content": message}]
    return [AIMessage(content=message)]


def _clean_address_text(value: object) -> str | None:
    """웹뷰/DB에서 온 주소 조각을 비교 가능한 문자열로 정리한다."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.split())


def _address_value(address: dict | None, snake_key: str, camel_key: str) -> str | None:
    """배송지 dict가 snake_case/camelCase 어느 쪽이어도 같은 값으로 읽는다."""
    if not address:
        return None
    return _clean_address_text(address.get(snake_key) or address.get(camel_key))


def _address_line(address: dict | None) -> str | None:
    """배송지의 line1/line2를 합쳐 비교와 안내 멘트에 쓸 한 줄 주소를 만든다."""
    if not address:
        return None
    line1 = _address_value(address, "address_line1", "addressLine1")
    line2 = _address_value(address, "address_line2", "addressLine2")
    full = " ".join(part for part in [line1, line2] if part)
    if full:
        return full
    return _clean_address_text(address.get("address") or address.get("fullAddress"))


def _same_address(left: dict | None, right: dict | None) -> bool:
    """현재 MVP에서는 주소 한 줄이 같으면 같은 배송지로 본다."""
    left_line = _address_line(left)
    right_line = _address_line(right)
    return bool(left_line and right_line and left_line == right_line)


def _webview_address_from_request(req: WebviewResultRequest) -> dict | None:
    """프론트 WebView가 긁어 보낸 배송지만 추출한다."""
    if isinstance(req.deliveryAddress, dict):
        address = req.deliveryAddress
    elif req.addressLine1 or req.addressLine2:
        address = {
            "recipient_name": req.recipientName,
            "recipient_phone": req.recipientPhone,
            "address_line1": req.addressLine1,
            "address_line2": req.addressLine2,
            "delivery_request": req.deliveryRequest,
        }
    else:
        return None

    if not _address_line(address):
        return None
    return address


def _address_create_payload(
    *,
    user_id: int,
    webview_address: dict,
    fallback_address: dict | None = None,
) -> dict:
    """웹뷰 배송지를 user_addresses에 저장할 수 있는 DB payload로 바꾼다."""
    recipient_name = (
        _address_value(webview_address, "recipient_name", "recipientName")
        or _address_value(fallback_address, "recipient_name", "recipientName")
        or "미확인"
    )
    recipient_phone = (
        _address_value(webview_address, "recipient_phone", "recipientPhone")
        or _address_value(fallback_address, "recipient_phone", "recipientPhone")
        or ""
    )
    return {
        "user_id": user_id,
        "address_label": "웹뷰 배송지",
        "recipient_name": recipient_name,
        "recipient_phone": recipient_phone,
        "zip_code": _address_value(webview_address, "zip_code", "zipCode"),
        "address_line1": (
            _address_value(webview_address, "address_line1", "addressLine1")
            or _address_line(webview_address)
        ),
        "address_line2": _address_value(webview_address, "address_line2", "addressLine2"),
        "delivery_request": _address_value(webview_address, "delivery_request", "deliveryRequest"),
        "is_default": True,
    }


async def handle_webview_result_db(
    db: AsyncSession,
    conversation_id: int,
    req: WebviewResultRequest,
):
    """웹뷰 결제 결과를 DB 주문/결제/구매이력 상태에 반영한다."""
    conversation = await conversation_repository.get_conversation_by_id_db(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })
    if req.orderId is None or req.paymentId is None:
        raise HTTPException(status_code=422, detail={
            "category": "PAYMENT_ERROR",
            "code": "WEBVIEW_RESULT_IDS_REQUIRED",
            "message": "웹뷰 결과 처리에는 orderId와 paymentId가 필요합니다.",
        })

    order = await order_repository.get_order_by_id_db(db, req.orderId)
    if not order or order.get("conversation_id") != conversation_id:
        raise HTTPException(status_code=404, detail={
            "category": "ORDER_ERROR",
            "code": "ORDER_NOT_FOUND",
            "message": "주문을 찾을 수 없습니다.",
        })

    payment = await payment_repository.get_payment_by_id_db(db, req.paymentId)
    if not payment or payment.get("order_id") != req.orderId:
        raise HTTPException(status_code=404, detail={
            "category": "PAYMENT_ERROR",
            "code": "PAYMENT_NOT_FOUND",
            "message": "결제를 찾을 수 없습니다.",
        })

    base = {
        "conversationId": conversation_id,
        "recommendationId": None,
        "recommendations": [],
        "selectedProduct": None,
        "pendingConfirmation": None,
        "availableOptions": None,
        "deliveryAddress": None,
        "cart": None,
        "asyncStatus": None,
    }
    order_payload = {"orderId": order["id"], "status": order["status"]}
    payment_payload = {
        "paymentId": payment["id"],
        "paymentStatus": payment["payment_status"],
    }

    def _full_address(address: dict | None) -> str | None:
        """배송지 dict를 사용자가 듣기 쉬운 한 줄 주소로 만든다."""
        return _address_line(address)

    async def _sync_webview_address_with_db() -> dict | None:
        """
        웹뷰에서 확인한 배송지를 기본 배송지로 반영한다.

        - 웹뷰 주소가 없으면 DB 기본 배송지만 사용한다.
        - 같은 주소가 DB에 있으면 그 주소를 기본 배송지로 올린다.
        - 없으면 웹뷰 주소를 새 기본 배송지로 저장한다.
        """
        webview_address = _webview_address_from_request(req)
        try:
            default_address = await address_repository.get_default_address_by_user_id_db(
                db,
                order["user_id"],
            )
        except Exception:
            default_address = None

        if not webview_address:
            return default_address

        try:
            existing_addresses = await address_repository.get_addresses_by_user_id_db(
                db,
                order["user_id"],
            )
        except Exception:
            existing_addresses = []

        for existing_address in existing_addresses:
            if _same_address(existing_address, webview_address):
                if not existing_address.get("is_default"):
                    updated_address = await address_repository.set_default_address_db(
                        db,
                        order["user_id"],
                        existing_address["id"],
                    )
                    return updated_address or existing_address
                return existing_address

        return await address_repository.create_address_db(
            db,
            _address_create_payload(
                user_id=order["user_id"],
                webview_address=webview_address,
                fallback_address=default_address,
            ),
        )

    async def _delivery_address_from_request_or_db() -> dict | None:
        """웹뷰 주소를 DB 기본 배송지와 동기화한 뒤 사용할 배송지를 반환한다."""
        synced_address = await _sync_webview_address_with_db()
        if synced_address:
            return synced_address
        try:
            return await address_repository.get_default_address_by_user_id_db(
                db,
                order["user_id"],
            )
        except Exception:
            return None

    result = req.result.lower()
    if result in {"success", "completed", "paid"}:
        updated_payment = await payment_repository.update_payment_status_db(
            db,
            req.paymentId,
            payment_status="paid",
        )
        updated_order = await order_repository.update_order_status_db(
            db,
            req.orderId,
            status="order_completed",
        )
        history_result = await purchase_history_service.create_histories_from_order_db(
            db,
            conversation_id=conversation_id,
            user_id=order["user_id"],
            payment_id=req.paymentId,
        )
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {
                "status": "order_completed",
                "stage": "completed",
                "ended_at": datetime.now(UTC),
            },
        )
        await agent_event_repository.create_agent_event_db(
            db,
            conversation_id=conversation_id,
            agent_name="payment_service",
            event_type="payment_completed",
            input_summary={"order_id": req.orderId, "payment_id": req.paymentId},
            output_summary={
                "order_status": updated_order["status"],
                "payment_status": updated_payment["payment_status"],
                "purchase_history_count": history_result.get("count", 0),
            },
        )
        webview_progress_service.clear_progress(conversation_id)
        await runtime.update_state(conversation_id, {
            "stage": "completed",
            "pending_action": None,
            "order": {"orderId": updated_order["id"], "status": updated_order["status"]},
            "payment": {
                "paymentId": updated_payment["id"],
                "paymentStatus": updated_payment["payment_status"],
            },
            "webview_progress": None,
            "messages": _assistant_message_patch("결제가 완료되었어요!"),
        })
        delivery_address = await _delivery_address_from_request_or_db()
        return {
            **base,
            "status": "order_completed",
            "stage": "completed",
            "assistantMessage": "결제가 완료되었어요!",
            "deliveryAddress": delivery_address,
            "order": {"orderId": updated_order["id"], "status": updated_order["status"]},
            "payment": {
                "paymentId": updated_payment["id"],
                "paymentStatus": updated_payment["payment_status"],
            },
            "uiCommand": {"type": "close_webview"},
            "error": None,
        }

    if result in {"payment_ready_mock", "payment_button_attempted", "payment_ready"}:
        message = "결제 버튼 누르기까지 시도했어요. 실제 결제 완료 여부는 쇼핑몰 화면에서 확인해주세요."
        updated_payment = await payment_repository.update_payment_status_db(
            db,
            req.paymentId,
            payment_status="payment_button_attempted",
        )
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {
                "status": "payment_button_attempted",
                "stage": "completed",
                "ended_at": datetime.now(UTC),
            },
        )
        await agent_event_repository.create_agent_event_db(
            db,
            conversation_id=conversation_id,
            agent_name="payment_service",
            event_type="payment_button_attempted",
            input_summary={
                "order_id": req.orderId,
                "payment_id": req.paymentId,
                "webview_result": result,
            },
            output_summary={
                "order_status": order["status"],
                "payment_status": updated_payment["payment_status"],
            },
        )
        webview_progress_service.clear_progress(conversation_id)
        await runtime.update_state(conversation_id, {
            "stage": "completed",
            "pending_action": None,
            "order": {"orderId": order["id"], "status": order["status"]},
            "payment": {
                "paymentId": updated_payment["id"],
                "paymentStatus": updated_payment["payment_status"],
            },
            "webview_progress": None,
            "messages": _assistant_message_patch(message),
        })
        delivery_address = await _delivery_address_from_request_or_db()
        return {
            **base,
            "status": "payment_button_attempted",
            "stage": "completed",
            "assistantMessage": message,
            "deliveryAddress": delivery_address,
            "order": {"orderId": order["id"], "status": order["status"]},
            "payment": {
                "paymentId": updated_payment["id"],
                "paymentStatus": updated_payment["payment_status"],
            },
            "uiCommand": {"type": "close_webview"},
            "error": None,
        }

    if result == "cart_added":
        webview_progress_service.clear_progress(conversation_id)
        message = "장바구니에 담았어요. 더 구매하실래요, 아니면 결제할까요?"
        state_patch = {
            "stage": "cart_shopping",
            "pending_action": {
                "type": "continue_shopping",
                "message": message,
                "payload": {
                    "subType": "continue_shopping",
                    "options": ["continue_shopping", "checkout"],
                },
            },
            "messages": _assistant_message_patch(message),
            "webview_progress": None,
            "order": order_payload,
            "payment": payment_payload,
        }
        await runtime.update_state(conversation_id, state_patch)
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {"status": "cart_shopping", "stage": "cart_shopping"},
        )
        return {
            **base,
            "status": "cart_shopping",
            "stage": "cart_shopping",
            "assistantMessage": message,
            "pendingConfirmation": {
                "type": "payment",
                "message": message,
                "payload": {
                    "subType": "continue_shopping",
                    "options": ["continue_shopping", "checkout"],
                },
            },
            "order": order_payload,
            "payment": payment_payload,
            "uiCommand": {"type": "close_webview"},
            "error": None,
        }

    if result == "address_checked":
        webview_progress_service.clear_progress(conversation_id)
        delivery_address = await _delivery_address_from_request_or_db()
        address_text = _full_address(delivery_address)
        message = (
            f"{address_text}로 배송해드릴까요?"
            if address_text
            else "배송지를 확인했어요. 이 배송지로 진행할까요?"
        )
        await runtime.update_state(conversation_id, {
            "stage": "address_confirming",
            "delivery_address": delivery_address,
            "pending_action": {
                "type": "address_confirm",
                "message": message,
                "payload": {"address": delivery_address},
            },
            "messages": _assistant_message_patch(message),
            "order": order_payload,
            "payment": payment_payload,
            "webview_progress": None,
        })
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {"status": "address_confirming", "stage": "address_confirming"},
        )
        return {
            **base,
            "status": "waiting_user_confirmation",
            "stage": "address_confirming",
            "assistantMessage": message,
            "pendingConfirmation": {
                "type": "address_confirm",
                "message": message,
                "payload": {"address": delivery_address},
            },
            "deliveryAddress": delivery_address,
            "order": order_payload,
            "payment": payment_payload,
            "uiCommand": {"type": "close_webview"},
            "error": None,
        }

    if result == "cancelled":
        updated_payment = await payment_repository.update_payment_status_db(
            db,
            req.paymentId,
            payment_status="cancelled",
        )
        updated_order = await order_repository.update_order_status_db(
            db,
            req.orderId,
            status="cancelled",
        )
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {
                "status": "cancelled",
                "stage": "cancelled",
                "ended_at": datetime.now(UTC),
            },
        )
        await agent_event_repository.create_agent_event_db(
            db,
            conversation_id=conversation_id,
            agent_name="payment_service",
            event_type="payment_cancelled",
            input_summary={"order_id": req.orderId, "payment_id": req.paymentId},
            output_summary={"order_status": updated_order["status"], "payment_status": updated_payment["payment_status"]},
        )
        webview_progress_service.clear_progress(conversation_id)
        await runtime.update_state(conversation_id, {
            "stage": "cancelled",
            "messages": _assistant_message_patch("결제가 취소되었습니다."),
            "pending_action": None,
            "order": {"orderId": updated_order["id"], "status": updated_order["status"]},
            "payment": {
                "paymentId": updated_payment["id"],
                "paymentStatus": updated_payment["payment_status"],
            },
            "webview_progress": None,
        })
        return {
            **base,
            "status": "cancelled",
            "stage": "cancelled",
            "assistantMessage": "결제가 취소되었습니다.",
            "order": {"orderId": updated_order["id"], "status": updated_order["status"]},
            "payment": {
                "paymentId": updated_payment["id"],
                "paymentStatus": updated_payment["payment_status"],
            },
            "uiCommand": None,
            "error": None,
        }

    updated_payment = await payment_repository.update_payment_status_db(
        db,
        req.paymentId,
        payment_status="failed",
        failure_reason="webview_result_failed",
    )
    updated_order = await order_repository.update_order_status_db(
        db,
        req.orderId,
        status="failed",
        failed_reason="webview_result_failed",
    )
    await conversation_repository.update_conversation_db(
        db,
        conversation_id,
        {
            "status": "failed",
            "stage": "failed",
            "ended_at": datetime.now(UTC),
        },
    )
    await agent_event_repository.create_agent_event_db(
        db,
        conversation_id=conversation_id,
        agent_name="payment_service",
        event_type="payment_failed",
        input_summary={"order_id": req.orderId, "payment_id": req.paymentId},
        output_summary={"order_status": updated_order["status"], "payment_status": updated_payment["payment_status"]},
    )
    webview_progress_service.clear_progress(conversation_id)
    await runtime.update_state(conversation_id, {
        "stage": "failed",
        "messages": _assistant_message_patch("결제에 실패했습니다."),
        "pending_action": None,
        "order": {"orderId": updated_order["id"], "status": updated_order["status"]},
        "payment": {
            "paymentId": updated_payment["id"],
            "paymentStatus": updated_payment["payment_status"],
        },
        "webview_progress": None,
        "error": "webview_result_failed",
    })
    return {
        **base,
        "status": "failed",
        "stage": "failed",
        "assistantMessage": "결제에 실패했습니다.",
        "order": {"orderId": updated_order["id"], "status": updated_order["status"]},
        "payment": {
            "paymentId": updated_payment["id"],
            "paymentStatus": updated_payment["payment_status"],
        },
        "uiCommand": None,
        "error": {
            "category": "PAYMENT_ERROR",
            "code": "PAYMENT_FAILED",
            "message": "결제 실패",
        },
    }

async def retry_payment_db(db: AsyncSession, order_id: int, req: PaymentRetryRequest):
    """기존 결제 레코드를 DB 기준으로 다시 pending 상태로 돌린다.

    실제 외부 결제 URL 재발급은 아직 연동하지 않고, 내부 결제 상태만 복구한다.
    """
    o = await order_repository.get_order_by_id_db(db, order_id)
    if not o:
        raise HTTPException(status_code=404, detail={"category": "ORDER_ERROR", "code": "ORDER_NOT_FOUND", "message": "주문을 찾을 수 없습니다."})

    items = await order_repository.get_order_items_by_order_id_db(db, order_id)
    main_product = items[0] if items else {}
    payment = await payment_repository.get_payment_by_order_id_db(db, order_id)
    if payment:
        payment = await payment_repository.update_payment_status_db(
            db,
            payment["id"],
            payment_status="pending_user_action",
        )
    else:
        bundle = await payment_repository.create_payment_for_order_db(
            db,
            order_id=order_id,
            payment_provider="internal",
            payment_method="manual",
            payment_status="pending_user_action",
        )
        payment = bundle["payment"]

    updated_order = await order_repository.update_order_status_db(
        db,
        order_id,
        status="payment_pending",
    )
    payment_url = payment.get("payment_url")
    return {
        "conversationId": req.conversationId or o.get("conversation_id"),
        "status": "payment_in_progress", "stage": "payment_password_required",
        "assistantMessage": "결제창을 다시 열어드릴게요.", "recommendationId": None, "recommendations": [],
        "selectedProduct": {"productName": main_product.get("product_name_snapshot", ""), "price": main_product.get("unit_price", 0), "optionText": main_product.get("option_snapshot"), "platform": o.get("platform", "internal")},
        "pendingConfirmation": {"type": "payment", "message": "결제창에서 인증을 완료해 주세요.", "payload": {"orderId": order_id, "paymentId": payment["id"]}},
        "availableOptions": None, "deliveryAddress": None,
        "order": {"orderId": order_id, "status": updated_order["status"], "productName": main_product.get("product_name_snapshot", ""), "optionText": main_product.get("option_snapshot"), "quantity": main_product.get("quantity", 1), "totalPaymentAmount": o.get("total_payment_amount", 0)},
        "payment": {"paymentId": payment["id"], "paymentStatus": payment["payment_status"], "paymentProvider": payment.get("payment_provider"), "paymentAmount": payment.get("payment_amount", 0)},
        "uiCommand": {"type": "open_webview", "target": "payment", "url": payment_url} if payment_url else None,
        "asyncStatus": None, "error": None
    }
