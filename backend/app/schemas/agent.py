from pydantic import BaseModel
from typing import Optional, List, Any

class RecommendationItemInAgent(BaseModel):
    recommendationItemId: int
    productId: int
    productName: str
    brand: Optional[str] = None
    price: int
    rank: int
    optionText: Optional[str] = None
    deliveryInfo: Optional[str] = None
    deliveryFee: Optional[int] = None
    rating: Optional[float] = None
    reviewCount: Optional[int] = None
    imageUrl: Optional[str] = None
    productUrl: Optional[str] = None
    platform: Optional[str] = None
    reason: Optional[str] = None
    isSelected: bool = False
    isOrderable: bool = True
    orderBlockReason: Optional[str] = None

class AgentResponse(BaseModel):
    conversationId: int
    status: str
    stage: str
    assistantMessage: str
    recommendationId: Optional[int] = None
    recommendations: List[RecommendationItemInAgent] = []
    selectedProduct: Optional[Any] = None
    pendingConfirmation: Optional[Any] = None
    availableOptions: Optional[Any] = None
    deliveryAddress: Optional[Any] = None
    order: Optional[Any] = None
    payment: Optional[Any] = None
    uiCommand: Optional[Any] = None
    asyncStatus: Optional[Any] = None
    error: Optional[Any] = None

class ShoppingRequest(BaseModel):
    userId: int
    message: str
    inputType: str = "text"

class MessageRequest(BaseModel):
    message: str
    inputType: str = "text"
    action: Optional[str] = None

class ConfirmRequest(BaseModel):
    recommendationItemId: int
    action: str  # order_now | add_to_cart | reject
