from app.repositories import order_repository, user_repository, payment_repository
from app.schemas.order import OrderDetailResponse, OrderSummary, OrderListResponse, OrderItemDetail, ShippingAddress, OrderPaymentInfo, OrderCancelRequest
from fastapi import HTTPException
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

def _iso(v) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else v


async def _to_detail_db(db: AsyncSession, o: dict) -> OrderDetailResponse:
    items = await order_repository.get_order_items_by_order_id_db(db, o["id"])
    payment = await payment_repository.get_payment_by_order_id_db(db, o["id"])
    shipping = ShippingAddress(
        recipientName=o.get("recipient_name_snapshot", ""),
        recipientPhone=o.get("recipient_phone_snapshot"),
        address=o.get("shipping_address_snapshot", ""),
        deliveryRequest=o.get("delivery_request_snapshot"),
    ) if o.get("shipping_address_snapshot") else None
    payment_info = OrderPaymentInfo(
        paymentId=payment["id"], paymentProvider=payment.get("payment_provider"),
        paymentMethod=payment.get("payment_method"), paymentStatus=payment.get("payment_status", ""),
        paymentAmount=payment.get("payment_amount", 0), paidAt=_iso(payment.get("paid_at"))
    ) if payment else None
    return OrderDetailResponse(
        orderId=o["id"], conversationId=o.get("conversation_id"), status=o["status"],
        platform=o.get("platform"), totalProductPrice=o.get("total_product_price", 0),
        deliveryFee=o.get("delivery_fee", 0), totalPaymentAmount=o.get("total_payment_amount", 0),
        confirmedAt=_iso(o.get("confirmed_at")), orderedAt=_iso(o.get("ordered_at")), shippingAddress=shipping,
        items=[OrderItemDetail(orderItemId=i["id"], productName=i["product_name_snapshot"],
                               optionText=i.get("option_snapshot"), unitPrice=i.get("unit_price", 0),
                               quantity=i["quantity"], totalPrice=i.get("total_price", 0)) for i in items],
        payment=payment_info,
    )

async def _to_summary_db(db: AsyncSession, o: dict) -> OrderSummary:
    items = await order_repository.get_order_items_by_order_id_db(db, o["id"])
    return OrderSummary(
        orderId=o["id"], conversationId=o.get("conversation_id"), status=o["status"],
        totalPaymentAmount=o.get("total_payment_amount", 0), orderedAt=_iso(o.get("ordered_at")),
        mainProductName=items[0]["product_name_snapshot"] if items else None, itemCount=len(items)
    )

async def get_order_db(db: AsyncSession, order_id: int) -> OrderDetailResponse:
    o = await order_repository.get_order_by_id_db(db, order_id)
    if not o:
        raise HTTPException(status_code=404, detail={"category": "ORDER_ERROR", "code": "ORDER_NOT_FOUND", "message": "주문을 찾을 수 없습니다."})
    return await _to_detail_db(db, o)

async def get_user_orders_db(db: AsyncSession, user_id: int, status: Optional[str] = None, limit: Optional[int] = None) -> OrderListResponse:
    if not await user_repository.get_user_by_id_db(db, user_id):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    orders = await order_repository.get_orders_by_user_id_db(db, user_id, status=status, limit=limit)
    return OrderListResponse(userId=user_id, orders=[await _to_summary_db(db, o) for o in orders])

async def cancel_order_db(db: AsyncSession, order_id: int, req: Optional[OrderCancelRequest] = None):
    o = await order_repository.update_order_status_db(
        db,
        order_id,
        status="cancelled",
        failed_reason=req.reason if req else None,
    )
    if not o:
        raise HTTPException(status_code=404, detail={"category": "ORDER_ERROR", "code": "ORDER_NOT_FOUND", "message": "주문을 찾을 수 없습니다."})
    conversation_id = (req.conversationId if req else None) or o.get("conversation_id")
    return {"conversationId": conversation_id, "status": "cancelled", "stage": "cancelled",
            "assistantMessage": "주문이 취소되었습니다.", "recommendationId": None, "recommendations": [],
            "selectedProduct": None, "pendingConfirmation": None, "availableOptions": None,
            "deliveryAddress": None, "order": {"orderId": o["id"], "status": "cancelled"},
            "payment": None, "uiCommand": None, "asyncStatus": None, "error": None}
