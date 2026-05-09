from pydantic import BaseModel
from typing import Optional

class PaymentDetailResponse(BaseModel):
    paymentId: int
    orderId: int
    paymentProvider: Optional[str] = None
    paymentMethod: Optional[str] = None
    paymentStatus: str
    paymentAmount: int
    externalPaymentId: Optional[str] = None
    approvalNumber: Optional[str] = None
    paidAt: Optional[str] = None
    cancelledAt: Optional[str] = None
    failureReason: Optional[str] = None

class WebviewResultRequest(BaseModel):
    orderId: int
    paymentId: int
    result: str

class PaymentRetryRequest(BaseModel):
    conversationId: Optional[int] = None
