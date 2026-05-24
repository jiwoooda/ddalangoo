from pydantic import BaseModel
from typing import Optional, List

class ShippingAddress(BaseModel):
    recipientName: str
    recipientPhone: Optional[str] = None
    address: str
    deliveryRequest: Optional[str] = None

class OrderItemDetail(BaseModel):
    orderItemId: int
    productName: str
    optionText: Optional[str] = None
    unitPrice: int
    quantity: int
    totalPrice: int

class OrderPaymentInfo(BaseModel):
    paymentId: int
    paymentProvider: Optional[str] = None
    paymentMethod: Optional[str] = None
    paymentStatus: str
    paymentAmount: int
    paidAt: Optional[str] = None

class OrderDetailResponse(BaseModel):
    orderId: int
    conversationId: Optional[int] = None
    status: str
    platform: Optional[str] = None
    totalProductPrice: int
    deliveryFee: int = 0
    totalPaymentAmount: int
    confirmedAt: Optional[str] = None
    orderedAt: Optional[str] = None
    shippingAddress: Optional[ShippingAddress] = None
    items: List[OrderItemDetail]
    payment: Optional[OrderPaymentInfo] = None

class OrderSummary(BaseModel):
    orderId: int
    conversationId: Optional[int] = None
    status: str
    totalPaymentAmount: int
    orderedAt: Optional[str] = None
    mainProductName: Optional[str] = None
    itemCount: int

class OrderListResponse(BaseModel):
    userId: int
    orders: List[OrderSummary]

class OrderCancelRequest(BaseModel):
    conversationId: Optional[int] = None
    reason: Optional[str] = None
