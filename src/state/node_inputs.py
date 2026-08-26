"""
노드별 최소 Read 계약 명시 (= 노드 의존 필드 타입 명시).

각 TypedDict은 해당 노드 함수가 실제로 읽는 ShoppingState 필드의 부분집합을
정적으로 문서화한 것이다 — **런타임에 다른 필드로의 접근을 차단하는 장치가
아니다.** 그래프 자체의 State는 여전히 ShoppingState 하나로 유지하고
(Subgraph로 쪼개지 않음), 각 노드에는 지금처럼 전체 ShoppingState 딕셔너리가
그대로 전달된다. TypedDict은 구조적 타이핑이라 필드가 더 많은 dict를 넘겨도
문제없다 — 완전한 보안 경계가 아니며, 민감정보는 애초에 ShoppingState
자체에 넣지 않아야 한다(이 계약을 좁힌다고 없던 격리가 생기지 않는다).

노드 함수의 타입 시그니처를 이 좁은 타입으로 선언하면 얻는 것:

  - 이 노드가 실제로 어떤 필드를 읽는지 코드만 보고 바로 알 수 있고
  - 결제 노드가 실수로 구매이력 전체 같은 무관한 필드를 참조하는 식의
    결합을 정적 타입체커가 잡아줄 수 있고
  - 나중에 정말 Subgraph로 분리해야 할 때, 이 타입이 그대로 해당 Subgraph의
    입력 스키마 초안이 된다

각 노드 파일의 `*_node` 진입점 함수만 이 타입으로 선언했다. 같은 파일 안의
private 헬퍼 함수(`_extract_user_input` 등)는 기존처럼 `ShoppingState`를 받는다
— 실무적으로 churn 대비 이득이 작아서 이번 범위에서는 안 건드렸다.
"""
from typing import Any, Literal, Optional, TypedDict

from src.state.schema import Condition, Intent, PendingAction, Stage


class IntentAgentInput(TypedDict):
    messages: list
    stage: Stage
    pending_action: Optional[PendingAction]
    keywords: list[str]
    quantity: Optional[int]
    recipe_dish: Optional[str]
    recipe_people: Optional[int]
    user_id: str
    cart_items: list[dict[str, Any]]


class ContextAgentInput(TypedDict):
    stage: Stage
    intent: Optional[Intent]
    user_id: str
    keywords: list[str]
    exclude_keywords: list[str]
    messages: list
    recommend_from_profile: bool


class ProductAgentInput(TypedDict):
    intent: Optional[Intent]
    keywords: list[str]
    exclude_keywords: list[str]
    condition: Optional[Condition]
    current_product_index: int
    recommended_products: list[dict[str, Any]]
    recommendation_context: Optional[dict[str, Any]]
    quantity: Optional[int]


class ResponseAgentInput(TypedDict):
    intent: Optional[Intent]
    keywords: list[str]
    condition: Optional[Condition]
    recommendation_context: Optional[dict[str, Any]]
    recommended_products: list[dict[str, Any]]
    current_product_index: int
    selected_product: Optional[dict[str, Any]]
    messages: list
    stage: Stage
    quantity: Optional[int]
    user_id: str


class ReorderAgentInput(TypedDict):
    pending_action: Optional[PendingAction]
    user_id: str
    keywords: list[str]
    messages: list


class RecipeAgentInput(TypedDict):
    stage: Stage
    recipe_dish: Optional[str]
    recipe_people: Optional[int]
    queue_items: list[dict[str, Any]]
    messages: list


class PurchaseQueueAgentInput(TypedDict):
    stage: Stage
    intent: Optional[Intent]
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    queue_source: Optional[Literal["recipe", "multi_buy"]]


class SmalltalkAgentInput(TypedDict):
    user_id: str
    messages: list
    onboarding_started_at: Optional[str]
    recent_patterns_used: list[str]
    recent_episodes_used: list[str]
    name_greeting_pending: bool
    consecutive_question_turns: int
    already_asked_topics: list[str]
    turns_without_required_progress: int
    health_followup_turns_remaining: int
    recent_replies: list[str]


class PaymentAgentInput(TypedDict):
    stage: Stage
    pending_action: Optional[PendingAction]
    user_id: str
    selected_product: Optional[dict[str, Any]]
    keywords: list[str]
    quantity: Optional[int]
    intent: Optional[Intent]
    address_text: Optional[str]
    conversation_id: Optional[int]
    payment_idempotency_key: Optional[str]
    cart_operations: list[dict[str, Any]]


class RespondNodeInput(TypedDict):
    stage: Stage
    intent: Optional[Intent]
    immediate_response: Optional[str]
    explanation: Optional[str]
    pending_action: Optional[PendingAction]
    needs_clarification: bool
    clarification_reason: Optional[str]
    error: Optional[str]
    fallback_stuck_turns: int


class CancelNodeInput(TypedDict):
    cart_items: list[dict[str, Any]]


class FallbackOrchestratorInput(TypedDict):
    stage: Stage
    intent: Optional[Intent]
    user_id: str
    pending_action: Optional[PendingAction]
    confidence: Optional[float]
    needs_clarification: bool
    clarification_reason: Optional[str]
    keywords: list[str]
    quantity: Optional[int]
    condition: Optional[Condition]
    exclude_keywords: list[str]
    recommendation_context: Optional[dict[str, Any]]
    messages: list
    fallback_stuck_turns: int


# ══════════════════════════════════════════════
# Write 계약 — 좁은 Read 타입 → Node → 명시된 Partial Update로 대칭을 맞춘다.
# LangGraph는 노드가 반환한 dict를 기존 state에 병합하므로 전부 부분 갱신
# (total=False)이다. 실제 코드가 이 필드 밖의 것(예: response_agent의
# reflection_passed/haiku_fallback/reflection_reason)도 리턴하는 경우가
# 있는데, 그건 ShoppingState에 선언 안 된 애드혹 필드라 별도로 각주만 남긴다.
# ══════════════════════════════════════════════


class IntentAgentUpdate(TypedDict, total=False):
    intent: Optional[Intent]
    keywords: list[str]
    exclude_keywords: list[str]
    negative_constraints: list[str]
    quantity: Optional[int]
    condition: Optional[str]
    recipe_dish: Optional[str]
    recipe_people: Optional[int]
    target_platforms: list[str]
    override_platform: Optional[str]
    current_option_value: Optional[str]
    address_text: Optional[str]
    needs_clarification: bool
    clarification_reason: Optional[str]
    confidence: float
    immediate_response: str
    last_agent: str
    tool_calls: Optional[list[dict[str, Any]]]
    tool_results: Optional[dict[str, Any]]
    degraded_mode: bool
    failure_stage: Optional[str]
    degradation_reason: Optional[str]
    recommend_from_profile: bool
    cart_operations: list[dict[str, Any]]
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    queue_source: Optional[Literal["recipe", "multi_buy"]]


class ContextAgentUpdate(TypedDict, total=False):
    last_agent: str
    recommendation_context: dict[str, Any]
    keywords: list[str]
    exclude_keywords: list[str]
    conversation_summary: str  # stage=="completed"일 때만


class ProductAgentUpdate(TypedDict, total=False):
    search_results: list[dict[str, Any]]
    search_query: str
    stage: Stage
    error: Optional[str]
    last_agent: str
    pending_action: Optional[PendingAction]
    selected_product: dict[str, Any]
    product_url: Optional[str]
    recommended_products: list[dict[str, Any]]
    current_product_index: int
    quantity: Optional[int]
    ranking_mode: Optional[str]
    degraded_mode: bool
    failure_stage: Optional[str]


class ResponseAgentUpdate(TypedDict, total=False):
    explanation: str
    pending_action: Optional[PendingAction]
    stage: Stage
    last_agent: str
    error: Optional[str]
    degraded_mode: bool
    failure_stage: Optional[str]
    needs_clarification: bool
    # ShoppingState에 선언되지 않은 애드혹 필드 — response_agent가 자체적으로
    # 붙이는 디버그/평가용 값 (reflection 통과 여부 등):
    # reflection_passed: bool, haiku_fallback: bool, reflection_reason: str


class ReorderAgentUpdate(TypedDict, total=False):
    selected_product: dict[str, Any]
    product_url: Optional[str]
    pending_action: Optional[PendingAction]
    stage: Stage
    error: Optional[str]
    search_results: list[dict[str, Any]]
    last_agent: str
    needs_clarification: bool
    clarification_reason: Optional[str]
    immediate_response: str


class RecipeAgentUpdate(TypedDict, total=False):
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    queue_source: Optional[Literal["recipe", "multi_buy"]]
    stage: Stage
    pending_action: Optional[PendingAction]
    needs_clarification: bool
    clarification_reason: Optional[str]
    last_agent: str
    error: Optional[str]
    degraded_mode: bool
    failure_stage: Optional[str]


class PurchaseQueueAgentUpdate(TypedDict, total=False):
    current_queue_index: int
    stage: Stage
    pending_action: Optional[PendingAction]
    intent: Optional[Intent]
    keywords: list[str]
    quantity: Optional[int]
    last_agent: str
    error: Optional[str]


class SmalltalkAgentUpdate(TypedDict, total=False):
    explanation: str
    immediate_response: str
    pending_action: Optional[PendingAction]
    stage: Stage
    last_agent: str
    error: Optional[str]
    degraded_mode: bool
    failure_stage: Optional[str]
    degradation_reason: Optional[str]
    onboarding_started_at: Optional[str]
    recent_patterns_used: list[str]
    recent_episodes_used: list[str]
    name_greeting_pending: bool
    consecutive_question_turns: int
    already_asked_topics: list[str]
    turns_without_required_progress: int
    health_followup_turns_remaining: int
    recent_replies: list[str]


class PaymentAgentUpdate(TypedDict, total=False):
    stage: Stage
    selected_product: dict[str, Any]
    cart_items: list[dict[str, Any]]
    pending_action: Optional[PendingAction]
    error: Optional[str]
    last_agent: str
    quantity: Optional[int]
    order_id: str
    storage_state_path: Optional[str]
    payment_idempotency_key: Optional[str]
    degraded_mode: bool
    failure_stage: Optional[str]
    degradation_reason: Optional[str]


class RespondNodeUpdate(TypedDict, total=False):
    messages: list
    fallback_stuck_turns: int


class FallbackOrchestratorUpdate(TypedDict, total=False):
    intent: Optional[Intent]
    confidence: float
    keywords: list[str]
    quantity: Optional[int]
    condition: Optional[Condition]
    exclude_keywords: list[str]
    recipe_dish: Optional[str]
    selected_product: Optional[dict[str, Any]]
    search_results: list[dict[str, Any]]
    product_url: Optional[str]
    explanation: Optional[str]
    highlight_specs: list[str]
    current_product_index: int
    pending_action: Optional[PendingAction]
    immediate_response: str
    needs_clarification: bool
    clarification_reason: Optional[str]
    fallback_stuck_turns: int
    last_agent: str
    error: Optional[str]
