from pydantic import BaseModel
from typing import Any, Optional

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
    orderId: Optional[int] = None
    paymentId: Optional[int] = None
    result: str
    addressLine1: Optional[str] = None
    addressLine2: Optional[str] = None
    recipientName: Optional[str] = None
    recipientPhone: Optional[str] = None
    deliveryRequest: Optional[str] = None
    deliveryAddress: Optional[Any] = None

class PaymentRetryRequest(BaseModel):
    conversationId: Optional[int] = None
