from fastapi import APIRouter, Query
from app.schemas.order import OrderDetailResponse, OrderListResponse, OrderCancelRequest
from app.schemas.agent import AgentResponse
from app.services import order_service
from typing import Optional

router = APIRouter(tags=["Orders"])

@router.get("/orders/{orderId}", response_model=OrderDetailResponse)
def get_order(orderId: int):
    return order_service.get_order(orderId)

@router.get("/users/{userId}/orders", response_model=OrderListResponse)
def get_user_orders(userId: int, status: Optional[str] = Query(None), limit: Optional[int] = Query(None)):
    return order_service.get_user_orders(userId, status=status, limit=limit)

@router.post("/orders/{orderId}/cancel", response_model=AgentResponse)
def cancel_order(orderId: int, req: OrderCancelRequest):
    return order_service.cancel_order(orderId, req)
