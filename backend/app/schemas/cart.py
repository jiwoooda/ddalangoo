from pydantic import BaseModel
from typing import Optional, List


class CartItemResponse(BaseModel):
    cartItemId: int
    productId: int
    productOptionId: Optional[int] = None
    productName: str
    optionText: Optional[str] = None
    unitPrice: int
    quantity: int
    totalPrice: int


class CartResponse(BaseModel):
    cartId: Optional[int]
    userId: int
    status: str
    items: List[CartItemResponse]


class SampleResponse(BaseModel):
    message: str
    createdCount: int
