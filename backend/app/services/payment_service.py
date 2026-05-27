from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import (
    agent_event_repository,
    conversation_repository,
    order_repository,
    payment_repository,
    purchase_history_repository,
)
from app.agent import runtime
from app.schemas.payment import PaymentDetailResponse, WebviewResultRequest, PaymentRetryRequest
from app.services import webview_progress_service
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
        approvalNumber=p.get("approval_number"), paidAt=p.get("paid_at"),
        cancelledAt=p.get("cancelled_at"), failureReason=p.get("failure_reason")
    )

def get_payment(payment_id: int) -> PaymentDetailResponse:
    p = payment_repository.get_payment_by_id(payment_id)
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

    result = req.result.lower()
    if result in {"success", "completed", "paid", "cart_added"}:
        webview_progress_service.clear_progress(conversation_id)
        # payment_processing으로 재개해야 라우터가 intent 무관하게 payment_agent로 직행한다.
        # cart_shopping을 쓰면 intent_agent가 stale 메시지를 분석해 엉뚱한 intent를 내놓을 수 있다.
        state = await runtime.inject_and_resume(conversation_id, {
            "stage": "payment_processing",
            "pending_action": None,
            "webview_progress": None,
        })
        from app.agent.mapper import state_to_response
        return state_to_response(state, conversation_id).model_dump(by_alias=True)

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

def retry_payment(order_id: int, req: PaymentRetryRequest):
    o = order_repository.get_order_by_id(order_id)
    if not o:
        raise HTTPException(status_code=404, detail={"category": "ORDER_ERROR", "code": "ORDER_NOT_FOUND", "message": "주문을 찾을 수 없습니다."})
    items = order_repository.get_order_items_by_order_id(order_id)
    main_product = items[0] if items else {}
    new_payment_id = 89
    return {
        "conversationId": req.conversationId or o.get("conversation_id"),
        "status": "payment_in_progress", "stage": "payment_password_required",
        "assistantMessage": "결제창을 다시 열어드릴게요.", "recommendationId": None, "recommendations": [],
        "selectedProduct": {"productName": main_product.get("product_name", ""), "price": main_product.get("unit_price", 0), "optionText": main_product.get("option_text"), "platform": o.get("platform", "naver")},
        "pendingConfirmation": {"type": "payment", "message": "결제창에서 인증을 완료해 주세요.", "payload": {"orderId": order_id, "paymentId": new_payment_id}},
        "availableOptions": None, "deliveryAddress": None,
        "order": {"orderId": order_id, "status": "payment_pending", "productName": main_product.get("product_name", ""), "optionText": main_product.get("option_text"), "quantity": main_product.get("quantity", 1), "totalPaymentAmount": o.get("total_payment_amount", 0)},
        "payment": {"paymentId": new_payment_id, "paymentStatus": "pending_user_action", "paymentProvider": "naverpay", "paymentAmount": o.get("total_payment_amount", 0)},
        "uiCommand": {"type": "open_webview", "target": "payment", "url": f"https://pay.naver.com/checkout/retry/{order_id}"},
        "asyncStatus": None, "error": None
    }
