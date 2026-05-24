from app.repositories import order_repository, user_repository, payment_repository
from app.schemas.order import OrderDetailResponse, OrderSummary, OrderListResponse, OrderItemDetail, ShippingAddress, OrderPaymentInfo, OrderCancelRequest
from fastapi import HTTPException
from typing import Optional

def _to_detail(o: dict) -> OrderDetailResponse:
    items = order_repository.get_order_items_by_order_id(o["id"])
    payment = payment_repository.get_payment_by_order_id(o["id"])
    shipping = ShippingAddress(
        recipientName=o.get("shipping_recipient_name", ""),
        recipientPhone=o.get("shipping_recipient_phone"),
        address=o.get("shipping_address", ""),
        deliveryRequest=o.get("delivery_request"),
    ) if o.get("shipping_address") else None
    payment_info = OrderPaymentInfo(
        paymentId=payment["id"], paymentProvider=payment.get("payment_provider"),
        paymentMethod=payment.get("payment_method"), paymentStatus=payment.get("payment_status", ""),
        paymentAmount=payment.get("payment_amount", 0), paidAt=payment.get("paid_at")
    ) if payment else None
    return OrderDetailResponse(
        orderId=o["id"], conversationId=o.get("conversation_id"), status=o["status"],
        platform=o.get("platform"), totalProductPrice=o.get("total_product_price", 0),
        deliveryFee=o.get("delivery_fee", 0), totalPaymentAmount=o.get("total_payment_amount", 0),
        confirmedAt=o.get("confirmed_at"), orderedAt=o.get("ordered_at"), shippingAddress=shipping,
        items=[OrderItemDetail(orderItemId=i["id"], productName=i["product_name"],
                               optionText=i.get("option_text"), unitPrice=i.get("unit_price", 0),
                               quantity=i["quantity"], totalPrice=i.get("total_price", 0)) for i in items],
        payment=payment_info,
    )

def _to_summary(o: dict) -> OrderSummary:
    items = order_repository.get_order_items_by_order_id(o["id"])
    return OrderSummary(
        orderId=o["id"], conversationId=o.get("conversation_id"), status=o["status"],
        totalPaymentAmount=o.get("total_payment_amount", 0), orderedAt=o.get("ordered_at"),
        mainProductName=items[0]["product_name"] if items else None, itemCount=len(items)
    )

def get_order(order_id: int) -> OrderDetailResponse:
    o = order_repository.get_order_by_id(order_id)
    if not o:
        raise HTTPException(status_code=404, detail={"category": "ORDER_ERROR", "code": "ORDER_NOT_FOUND", "message": "주문을 찾을 수 없습니다."})
    return _to_detail(o)

def get_user_orders(user_id: int, status: Optional[str] = None, limit: Optional[int] = None) -> OrderListResponse:
    if not user_repository.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    orders = order_repository.get_orders_by_user_id(user_id)
    if status:
        orders = [o for o in orders if o["status"] == status]
    if limit:
        orders = orders[:limit]
    return OrderListResponse(userId=user_id, orders=[_to_summary(o) for o in orders])

def cancel_order(order_id: int, req: Optional[OrderCancelRequest] = None):
    o = order_repository.cancel_order(order_id)
    if not o:
        raise HTTPException(status_code=404, detail={"category": "ORDER_ERROR", "code": "ORDER_NOT_FOUND", "message": "주문을 찾을 수 없습니다."})
    conversation_id = (req.conversationId if req else None) or o.get("conversation_id")
    return {"conversationId": conversation_id, "status": "cancelled", "stage": "cancelled",
            "assistantMessage": "주문이 취소되었습니다.", "recommendationId": None, "recommendations": [],
            "selectedProduct": None, "pendingConfirmation": None, "availableOptions": None,
            "deliveryAddress": None, "order": {"orderId": o["id"], "status": "cancelled"},
            "payment": None, "uiCommand": None, "asyncStatus": None, "error": None}
