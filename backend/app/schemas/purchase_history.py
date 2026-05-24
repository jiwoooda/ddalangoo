from pydantic import BaseModel
from typing import Any, Optional, List

class PurchaseHistoryItem(BaseModel):
    purchaseHistoryId: int
    productName: str
    brand: Optional[str] = None
    category: Optional[str] = None
    optionText: Optional[str] = None
    selectedOptions: Optional[dict[str, Any]] = None
    productUrl: Optional[str] = None
    priceAtPurchase: int
    quantity: int
    totalPrice: int
    platform: Optional[str] = None
    purchasedAt: str
    satisfaction: Optional[int] = None
    memo: Optional[str] = None

class PurchaseHistoryListResponse(BaseModel):
    userId: int
    histories: List[PurchaseHistoryItem]

class PurchaseHistoryDetailResponse(BaseModel):
    purchaseHistoryId: int
    userId: int
    productId: int
    productOptionId: Optional[int] = None
    platform: Optional[str] = None
    productName: str
    brand: Optional[str] = None
    category: Optional[str] = None
    optionText: Optional[str] = None
    selectedOptions: Optional[dict[str, Any]] = None
    productUrl: Optional[str] = None
    priceAtPurchase: int
    quantity: int
    totalPrice: int
    purchasedAt: str
    satisfaction: Optional[int] = None
    memo: Optional[str] = None
