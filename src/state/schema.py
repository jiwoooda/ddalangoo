from typing import Annotated, Optional, TypedDict, Literal, Any
from langgraph.graph.message import add_messages

# ══════════════════════════════════════════════
# 공통 타입
# ══════════════════════════════════════════════

Stage = Literal[
    "idle",
    "searching",
    "product_confirming",
    "cart_shopping",        # 장바구니 담긴 후 추가 쇼핑 여부 대기
    "payment_processing",
    "completed",
    "failed",
]

Intent = Literal[
    "buy",
    "reorder",
    "confirm",
    "deny",
    "next",
    "refine",
    "compare_platforms",
    "quantity_change",
    "address_change",
    "option_select",
    "ask",
    "cancel",
    "unclear",
]

Condition = Literal[
    "최저가",
    "가성비",
    "빠른배송",
    "인기순",
    "무료배송",
    "리뷰좋은",
]

PendingActionType = Literal[
    "product_confirm",
    "clarification",
    "payment_confirm",
    "option_select",
    "address_confirm",
    "price_change_confirm",
    "quantity_confirm",
    "continue_shopping",
]

class PendingAction(TypedDict, total=False):
    type: PendingActionType
    payload: dict[str, Any]
    message: str
    expires_at: Optional[str]

# ══════════════════════════════════════════════
# 1. ShoppingState — Intent + Platform + Product 전용
# ══════════════════════════════════════════════

class ShoppingState(TypedDict):
    # ── 대화 ──
    messages: Annotated[list, add_messages]

    # ── 플로우 제어 ──
    stage: Stage
    intent: Optional[Intent]
    last_agent: Optional[str]
    error: Optional[str]

    # ── Intent Agent 출력 ──
    confidence: Optional[float]
    immediate_response: Optional[str]
    needs_clarification: bool
    clarification_reason: Optional[str]

    # ── 검색 조건 ──
    keywords: list[str]
    exclude_keywords: list[str]
    negative_constraints: list[str]
    quantity: Optional[int]
    condition: Optional[Condition]

    # ── 플랫폼 ──
    override_platform: Optional[str]
    target_platforms: list[str]
    tried_platforms: list[str]
    selected_platform: Optional[str]

    # ── 상품 탐색 ──
    search_results: list[dict[str, Any]]
    scored_products: list[dict[str, Any]]
    recommended_products: list[dict[str, Any]]
    current_product_index: int
    selected_product: Optional[dict[str, Any]]
    product_url: Optional[str]
    explanation: Optional[str]
    highlight_specs: list[str]

    # ── 확인/대기 액션 ──
    pending_action: Optional[PendingAction]

    # ── 세션 식별자 ──
    session_id: str
    conversation_id: Optional[int]
    user_id: str

    # ── 브라우저 세션 (장바구니 storageState 유지) ──
    storage_state_path: Optional[str]

    # ── Memory Agent → Platform/Product 전달 context ──
    recommendation_context: Optional[dict[str, Any]]

    # ── Intent Agent 슬롯 (bridge 없이 payment agent로 전달) ──
    # spec의 intent_agent_node 반환값에 명시되어 있으나 ShoppingState에 누락된 필드
    current_option_value: Optional[str]
    address_text: Optional[str]

# ══════════════════════════════════════════════
# 2. PaymentState — Payment Subgraph 전용
# ══════════════════════════════════════════════

PaymentStage = Literal[
    "idle",
    "validate_input",
    "open_product_page",
    "option_selecting",
    "option_confirming",
    "cart",
    "address_confirming",
    "payment_precheck",
    "payment_password_required",
    "processing",
    "success",
    "failed",
]

PaymentStatus = Literal[
    "pending",
    "pending_user_action",
    "processing",
    "success",
    "failed",
]

class PaymentState(TypedDict):
    # ── 식별자 ──
    user_id: str
    conversation_id: Optional[int]

    # ── 구매 대상 ──
    selected_product: dict[str, Any]
    product_url: str
    quantity: int
    selected_platform: Optional[str]

    # ── 옵션 ──
    available_options: list[dict[str, Any]]
    current_option_index: int
    current_option_key: Optional[str]
    current_option_value: Optional[str]
    selected_options: dict[str, Any]

    # ── 배송지 ──
    delivery_address: Optional[dict[str, Any]]
    address_confirmed: bool

    # ── 결제/브라우저 ──
    playwright_session: Optional[str]
    checkout_session_id: Optional[str]
    order_id: Optional[str]

    payment_stage: PaymentStage
    payment_status: PaymentStatus
    payment_step: Optional[str]
    payment_retry: int
    payment_error: Optional[str]

    # ── 확인/대기 액션 ──
    pending_action: Optional[dict[str, Any]]

# ══════════════════════════════════════════════
# 3. MemoryState — Memory Agent 전용
# ══════════════════════════════════════════════

class MemoryState(TypedDict):
    user_id: str

    user_profile: dict[str, Any]
    purchase_history: list[dict[str, Any]]
    preference_memory: dict[str, Any]
    collective_context: Optional[dict[str, Any]]
    conversation_summary: Optional[str]

# ══════════════════════════════════════════════
# 4. RecommendationContext — 추천 검색 Layer 결과
# ══════════════════════════════════════════════

class RecommendationContext(TypedDict):
    keyword_results: list[dict[str, Any]]
    personal_vector_results: list[dict[str, Any]]
    collective_vector_results: list[dict[str, Any]]
    merged_context: list[dict[str, Any]]
    retrieval_mode: Literal[
        "keyword_only",
        "keyword_collective",
        "hybrid_personal_collective",
    ]

# ══════════════════════════════════════════════
# 5. Bridge Functions
# ══════════════════════════════════════════════

def bridge_memory_to_shopping(memory: MemoryState) -> dict:
    """
    Memory 결과를 ShoppingState에 직접 과도하게 주입하지 않는다.
    Agent 호출 시 context로 넘기는 것을 기본으로 한다.
    """
    return {
        "last_agent": "memory_agent",
    }


def bridge_shopping_to_payment(
    state: ShoppingState,
    delivery_address: Optional[dict[str, Any]] = None,
) -> PaymentState:
    """
    ShoppingState에서 결제에 필요한 최소 정보만 PaymentState로 변환한다.
    옵션/주소/결제 진행 상태는 PaymentState에서만 관리한다.
    """
    selected_product = state.get("selected_product") or {}
    product_url = (
        state.get("product_url")
        or selected_product.get("product_url")
        or selected_product.get("url")
        or ""
    )

    return {
        "user_id": state["user_id"],
        "conversation_id": state.get("conversation_id"),

        "selected_product": selected_product,
        "product_url": product_url,
        "quantity": state.get("quantity") or 1,
        "selected_platform": state.get("selected_platform"),

        "available_options": [],
        "current_option_index": 0,
        "current_option_key": None,
        "current_option_value": None,
        "selected_options": {},

        "delivery_address": delivery_address,
        "address_confirmed": False,

        "playwright_session": None,
        "checkout_session_id": None,
        "order_id": None,

        "payment_stage": "validate_input",
        "payment_status": "pending",
        "payment_step": None,
        "payment_retry": 0,
        "payment_error": None,

        "pending_action": None,
    }


def bridge_payment_to_shopping(payment: PaymentState) -> dict:
    """
    PaymentState 결과 중 ShoppingState에 필요한 결과만 반영한다.
    Payment 내부 세부 상태는 ShoppingState로 역류시키지 않는다.
    """
    if payment["payment_status"] == "success":
        return {
            "stage": "completed",
            "error": None,
            "last_agent": "payment_agent",
        }

    if payment["payment_status"] == "failed":
        return {
            "stage": "failed",
            "error": payment.get("payment_error"),
            "last_agent": "payment_agent",
        }

    return {
        "stage": "payment_processing",
        "error": payment.get("payment_error"),
        "last_agent": "payment_agent",
        "pending_action": payment.get("pending_action"),
    }


def get_default_shopping_state(user_id: str, session_id: str) -> dict:
    """테스트/초기화용 기본 ShoppingState 생성."""
    return {
        "messages": [],
        "stage": "idle",
        "intent": None,
        "last_agent": None,
        "error": None,
        "confidence": None,
        "immediate_response": None,
        "needs_clarification": False,
        "clarification_reason": None,
        "keywords": [],
        "exclude_keywords": [],
        "negative_constraints": [],
        "quantity": None,
        "condition": None,
        "override_platform": None,
        "target_platforms": [],
        "tried_platforms": [],
        "selected_platform": None,
        "search_results": [],
        "scored_products": [],
        "recommended_products": [],
        "current_product_index": 0,
        "selected_product": None,
        "product_url": None,
        "explanation": None,
        "highlight_specs": [],
        "pending_action": None,
        "session_id": session_id,
        "conversation_id": None,
        "user_id": user_id,
        "recommendation_context": None,
        "storage_state_path": None,
        "current_option_value": None,
        "address_text": None,
    }
