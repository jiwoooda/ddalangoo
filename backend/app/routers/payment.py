from fastapi import APIRouter
from app.schemas.payment import PaymentDetailResponse, PaymentRetryRequest
from app.services import payment_service

router = APIRouter(tags=["Payments"])

@router.get("/payments/{paymentId}", response_model=PaymentDetailResponse)
def get_payment(paymentId: int):
    return payment_service.get_payment(paymentId)

@router.post("/orders/{orderId}/payments/retry")
def retry_payment(orderId: int, req: PaymentRetryRequest):
    return payment_service.retry_payment(orderId, req)
