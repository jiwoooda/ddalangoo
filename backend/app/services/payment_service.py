from app.repositories import payment_repository, order_repository, conversation_repository
from app.services import purchase_history_service
from app.schemas.payment import PaymentDetailResponse, WebviewResultRequest, PaymentRetryRequest
from fastapi import HTTPException

def _save_purchase_histories(conversation_id: int, user_id: int) -> None:
    purchase_history_service.create_histories_from_order(conversation_id, user_id)


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
        _save_purchase_histories(conversation_id, conv.get("user_id"))
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
