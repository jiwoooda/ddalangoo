from pydantic import BaseModel, Field
from typing import Any, Optional, List


class AccessibilityPurchaseHistoryImportItem(BaseModel):
    """Accessibility 자동화가 수집한 구매이력 1건이다."""

    platform: str
    sourceType: Optional[str] = None
    productName: Optional[str] = None
    price: Optional[int] = None
    quantity: Optional[int] = None
    purchaseDate: Optional[str] = None
    imageUrl: Optional[str] = None
    orderNumber: Optional[str] = None
    productOrderId: Optional[str] = None
    deliveryStatus: Optional[str] = None
    deliveryType: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    keyword: Optional[str] = None
    optionText: Optional[str] = None
    productUrl: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AccessibilityPurchaseHistoryImportRequest(BaseModel):
    """Accessibility 자동화 구매이력 저장 요청이다."""

    items: List[AccessibilityPurchaseHistoryImportItem]


class AccessibilityPurchaseHistoryImportResponse(BaseModel):
    """Accessibility 자동화 구매이력 저장 결과다."""

    success: bool
    count: int
    historyIds: List[int]
    skippedCount: int
    skippedItems: List[dict[str, Any]]


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
    productId: Optional[int] = None
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
