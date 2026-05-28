from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.order import OrderDetailResponse, OrderListResponse, OrderCancelRequest
from app.schemas.agent import AgentResponse
from app.services import order_service
from typing import Optional

router = APIRouter(tags=["Orders"])

@router.get("/orders/{orderId}", response_model=OrderDetailResponse)
async def get_order(orderId: int, db: AsyncSession = Depends(get_db)):
    return await order_service.get_order_db(db, orderId)

@router.get("/users/{userId}/orders", response_model=OrderListResponse)
async def get_user_orders(
    userId: int,
    status: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await order_service.get_user_orders_db(db, userId, status=status, limit=limit)

@router.post("/orders/{orderId}/cancel", response_model=AgentResponse)
async def cancel_order(orderId: int, req: OrderCancelRequest, db: AsyncSession = Depends(get_db)):
    return await order_service.cancel_order_db(db, orderId, req)
