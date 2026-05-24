from pydantic import BaseModel
from typing import Optional, List

class RecommendationItemDetail(BaseModel):
    recommendationItemId: int
    rank: int
    productName: str
    brand: Optional[str] = None
    price: int
    optionText: Optional[str] = None
    deliveryInfo: Optional[str] = None
    imageUrl: Optional[str] = None
    reason: Optional[str] = None
    isSelected: bool = False
    isOrderable: bool = True
    orderBlockReason: Optional[str] = None

class RecommendationResponse(BaseModel):
    recommendationId: int
    conversationId: int
    status: Optional[str] = None
    summary: Optional[str] = None
    items: List[RecommendationItemDetail]
