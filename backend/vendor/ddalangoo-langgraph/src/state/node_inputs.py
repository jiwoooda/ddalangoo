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
from src.recovery.types import FailureEvent, ProgressSignature, RecoveryStatus


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
    product_request: Optional[dict[str, Any]]


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
    pending_action: Optional[PendingAction]
    question_classification: Optional[dict[str, Any]]  # WON-38 Unit 2 — Unit 4에서 소비


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
    queue_clear_existing: bool
    messages: list
    product_request: Optional[dict[str, Any]]
    question_classification: Optional[dict[str, Any]]  # WON-38 Unit 2 — Unit 3에서 소비


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
    # WON-30 — 이 필드가 빠져 있어서 respond_node(WON-24)의 "누가 마지막으로
    # needs_clarification을 확정했는지" 판단 로직이 그래프 실행 시 조용히
    # 무력화됐다(last_agent가 항상 None으로 들어와 last_agent=="intent_agent"
    # 분기가 절대 안 탐 → pending_action.message가 항상 우선됨).
    last_agent: Optional[str]


class CancelNodeInput(TypedDict):
    user_id: str
    cart_items: list[dict[str, Any]]


class FallbackOrchestratorInput(TypedDict):
    stage: Stage
    intent: Optional[Intent]
    user_id: str
    pending_action: Optional[PendingAction]
    confidence: Optional[float]
    needs_clarification: bool
    clarification_reason: Optional[str]
    goal_shift: bool  # WON-20 Unit 3 — Unit 2(intent_agent)가 out_of_scope로 본 경우 True
    keywords: list[str]
    quantity: Optional[int]
    condition: Optional[Condition]
    exclude_keywords: list[str]
    recommendation_context: Optional[dict[str, Any]]
    messages: list
    fallback_stuck_turns: int
    error: Optional[str]
    active_failure: Optional[FailureEvent]


class FailureDetectorInput(TypedDict):
    """Minimum state needed to produce one deterministic FailureEvent."""

    stage: Stage
    intent: Optional[Intent]
    pending_action: Optional[PendingAction]
    error: Optional[str]
    needs_clarification: bool
    active_failure: Optional[FailureEvent]


class FailureDetectorUpdate(TypedDict, total=False):
    active_failure: Optional[FailureEvent]


class TurnOutcomeGuardInput(TypedDict):
    """Minimum stable state used to compare progress across user turns."""

    stage: Stage
    intent: Optional[Intent]
    pending_action: Optional[PendingAction]
    current_queue_index: int
    queue_items: list[dict[str, Any]]
    selected_product: Optional[dict[str, Any]]
    cart_items: list[dict[str, Any]]
    order_id: Optional[str]
    payment: Optional[dict[str, Any]]
    active_failure: Optional[FailureEvent]
    turn_start_signature: Optional[ProgressSignature]
    last_turn_signature: Optional[ProgressSignature]
    repeated_signature_turns: int
    immediate_response: Optional[str]
    explanation: Optional[str]
    needs_clarification: bool
    last_agent: Optional[str]
    clarification_reason: Optional[str]
    quantity: Optional[int]
    address_text: Optional[str]
    error: Optional[str]


class TurnOutcomeGuardUpdate(TypedDict, total=False):
    active_failure: Optional[FailureEvent]
    last_turn_signature: Optional[ProgressSignature]
    repeated_signature_turns: int


class RecoveryOrchestratorInput(TypedDict):
    """Recovery policy receives only the event, budget, and safe state context."""

    stage: Stage
    pending_action: Optional[PendingAction]
    active_failure: Optional[FailureEvent]
    recovery_fingerprint: Optional[str]
    recovery_attempts: int
    recovery_status: RecoveryStatus


class RecoveryOrchestratorUpdate(TypedDict, total=False):
    recovery_fingerprint: Optional[str]
    recovery_attempts: int
    recovery_status: RecoveryStatus


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
    question_classification: Optional[dict[str, Any]]  # WON-38 Unit 2
    scope: Optional[str]  # WON-20 Unit 2 — "in_scope"|"bridgeable"|"out_of_scope"
    goal_shift: bool  # WON-20 Unit 2 — Unit 3(fallback_orchestrator)에서 소비
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
    product_request: Optional[dict[str, Any]]
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    queue_source: Optional[Literal["recipe", "multi_buy"]]
    queue_clear_existing: bool


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
    # WON-23 Unit 3/4 — product_decision_advice 응답 텍스트를 respond_node의
    # 최종 fallback 분기(immediate_response)로 그대로 넘길 때만 채운다.
    immediate_response: str
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
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    stage: Stage
    pending_action: Optional[PendingAction]
    intent: Optional[Intent]
    keywords: list[str]
    quantity: Optional[int]
    product_request: Optional[dict[str, Any]]
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
    intent: Optional[Intent]
    selected_product: dict[str, Any]
    keywords: list[str]
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
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    queue_source: Optional[Literal["recipe", "multi_buy"]]
    queue_clear_existing: bool


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
