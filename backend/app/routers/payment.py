from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.payment import PaymentDetailResponse, PaymentRetryRequest
from app.services import payment_service

router = APIRouter(tags=["Payments"])

@router.get("/payments/{paymentId}", response_model=PaymentDetailResponse)
async def get_payment(paymentId: int, db: AsyncSession = Depends(get_db)):
    return await payment_service.get_payment_db(db, paymentId)

@router.post("/orders/{orderId}/payments/retry")
async def retry_payment(orderId: int, req: PaymentRetryRequest, db: AsyncSession = Depends(get_db)):
    return await payment_service.retry_payment_db(db, orderId, req)
