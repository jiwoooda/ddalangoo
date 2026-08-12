from pydantic import BaseModel, Field
from typing import Optional, List, Any, Literal

class RecommendationItemInAgent(BaseModel):
    recommendationItemId: Optional[int] = None
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

class AutomationTaskInAgent(BaseModel):
    contractVersion: int = 1
    taskId: str
    taskType: str
    conversationId: Optional[int] = None
    userId: Optional[int] = None
    platform: Optional[str] = None
    packageName: Optional[str] = None
    currentStep: Optional[str] = None
    targetProductName: Optional[str] = None
    searchKeyword: Optional[str] = None
    optionName: Optional[str] = None
    quantity: int = 1
    cartItemId: Optional[str] = None
    orderId: Optional[int] = None
    paymentId: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class AutomationResultInAgent(BaseModel):
    contractVersion: int = 1
    taskId: str
    taskType: Optional[str] = None
    status: str
    platform: Optional[str] = None
    packageName: Optional[str] = None
    currentStep: Optional[str] = None
    resultType: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class AutomationResultRequest(BaseModel):
    contractVersion: int = 1
    taskId: str
    status: Literal["completed", "failed", "requires_user_action", "needs_user_confirmation"]
    taskType: Optional[str] = None
    currentStep: Optional[str] = None
    platform: Optional[str] = None
    packageName: Optional[str] = None
    resultType: Optional[str] = None
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

class AutomationVlmPlanRequest(BaseModel):
    taskId: str
    currentStep: str
    platform: str
    packageName: Optional[str] = None
    currentScreen: Optional[str] = None
    recoveryGoal: Optional[str] = None
    fallbackReasonCode: str
    expectedState: Optional[str] = None
    observedState: Optional[str] = None
    uiTreeSummary: str
    recentActions: List[Any] = []
    screenshot: str

class AutomationVlmPlanResponse(BaseModel):
    action: Literal["tap", "tap_coordinate", "tap_node", "back", "swipe", "wait", "abort", "none"]
    targetDescription: Optional[str] = None
    nodeId: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    direction: Optional[Literal["up", "down", "left", "right"]] = None
    distance: Optional[float] = None
    confidence: float = 0.0
    reason: str

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
    cart: Optional[Any] = None
    order: Optional[Any] = None
    payment: Optional[Any] = None
    uiCommand: Optional[Any] = None
    automationTask: Optional[AutomationTaskInAgent] = None
    automationResult: Optional[AutomationResultInAgent] = None
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
    recommendationItemId: Optional[int] = None
    action: str  # order_now | add_to_cart | reject
