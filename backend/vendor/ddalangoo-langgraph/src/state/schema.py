from typing import Annotated, Optional, TypedDict, Literal, Any
from langgraph.graph.message import add_messages

# ══════════════════════════════════════════════
# 공통 타입
# ══════════════════════════════════════════════

Stage = Literal[
    "idle",
    "searching",
    "product_confirming",
    "cart_shopping",
    "recipe_planning",
    "payment_processing",
    "payment_password_required",
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
    "product_select",
    "clarification",
    "payment_confirm",
    "address_confirm",
    "address_required",
    "price_change_confirm",
    "continue_shopping",
    "what_to_buy",
    "no_more_products",
    "cart_review",
    "ingredient_confirm",
    "payment_method_confirm",
    "payment_password",
    "payment_retry_confirm",
]

class PendingAction(TypedDict, total=False):
    type: PendingActionType
    payload: dict[str, Any]
    message: str
    expires_at: Optional[str]

# ══════════════════════════════════════════════
# 1. ShoppingState
# ══════════════════════════════════════════════

class ShoppingState(TypedDict):
    # ── 대화 ──
    messages: Annotated[list, add_messages]

    # ── 플로우 제어 ──
    stage: Stage
    intent: Optional[Intent]
    last_agent: Optional[str]
    error: Optional[str]

    # ── 실패 관측성(이번 턴 결과 요약) ── attempt_count/fallback_path처럼
    # 노드·시도 횟수에 종속적인 값은 여기 넣지 않는다 — JSONL 로그와
    # runtime.execution_info.node_attempt로만 추적한다(docs/resilience_plan.md
    # Phase 2 참고). 매 턴 시작 시 reset_turn_observability_node가 초기화한다.
    degraded_mode: bool
    degradation_reason: Optional[str]
    failure_stage: Optional[str]  # "intent_llm" | "scoring_llm" | "search" | ...
    ranking_mode: Optional[str]  # "llm" | "baseline"
    source_used: Optional[str]  # "remote_mcp" | "local_mcp" | "naver_api" | "kurly_url_fallback"

    # ── Intent Agent 출력 ──
    confidence: Optional[float]
    immediate_response: Optional[str]
    needs_clarification: bool
    clarification_reason: Optional[str]
    # "아무거나 사주세요"처럼 상품명 없이 dismissive하게 답할 때, 되묻는 대신
    # 프로필의 favorite_foods로 대신 채우라는 intent_agent → context_agent 신호.
    # intent_agent가 매 턴 명시적으로 True/False를 다시 쓴다(과거 턴 값이 이번
    # 턴에 새어들지 않도록) — quantity/needs_clarification과 동일한 패턴.
    recommend_from_profile: bool

    # ── Fallback Orchestrator 트리거 카운터 ── respond_node가 매 턴 갱신한다:
    # needs_clarification 계열(막힌) 분기를 타면 +1, 그 외 정상 분기를 타면 0.
    # smalltalk의 consecutive_question_turns와 같은 패턴(reset_turn_observability_node
    # 처럼 매 턴 강제 초기화하지 않음 — 연속성이 핵심). route()가 이 값을 보고
    # 이미 한 번 정해진 재질문을 했는데도 또 막혔으면 fallback_orchestrator로 보낸다.
    fallback_stuck_turns: int

    # ── 검색 조건 ──
    keywords: list[str]
    search_query: Optional[str]
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

    # ── 백엔드 결과 ──
    cart: Optional[dict[str, Any]]
    order: Optional[dict[str, Any]]
    payment: Optional[dict[str, Any]]
    checkout_session: Optional[dict[str, Any]]
    # 결제 플로우 진입 시 1회 생성, 이후 턴에서 재사용 — mock_place_order가
    # 동일 키+동일 요청 해시면 기존 주문을 반환하도록 중복 생성을 막는다.
    payment_idempotency_key: Optional[str]

    # ── 세션 식별자 ──
    session_id: str
    conversation_id: Optional[int]
    user_id: str

    # ── 브라우저 세션 (mock) ──
    storage_state_path: Optional[str]
    cart_items: list[dict[str, Any]]

    # ── 레시피 쇼핑 ──
    recipe_dish: Optional[str]
    recipe_people: Optional[int]
    recipe_items: list[dict[str, Any]]
    current_recipe_item_index: int

    # ── Memory Agent context ──
    recommendation_context: Optional[dict[str, Any]]
    reorder_resolution: Optional[dict[str, Any]]

    # ── Intent Agent 슬롯 ──
    current_option_value: Optional[str]
    address_text: Optional[str]
    tool_calls: Optional[list[dict[str, Any]]]
    tool_results: Optional[dict[str, Any]]
    conversation_summary: Optional[str]
    order_id: Optional[str]

    # ── 스몰토크 온보딩 이벤트 타이머 ── 온보딩 1턴째(smalltalk_agent)에
    # 찍고, 이후 턴마다 경과 시간을 재서 너무 길어지면(_MAX_ONBOARDING_MINUTES)
    # 강제 종료하는 안전장치용. 온보딩이 끝나면(onboarded_at 기록) 더 이상
    # 쓰이지 않는다.
    onboarding_started_at: Optional[str]

    # ── 스몰토크 화법 패턴 로테이션 ── 최근 2~3턴에 쓴 SMALLTALK_STYLE_PATTERNS
    # 키를 기록해서, 같은 화법이 연속으로 반복되지 않게 한다(select_style_pattern
    # 참고). 온보딩이 끝나면 더 이상 안 쓰인다.
    recent_patterns_used: list[str]

    # ── 스몰토크 에피소드 소재 로테이션 ── 최근 2~3턴에 쓴
    # SMALLTALK_EPISODE_BANK 키를 기록해서, 같은 자기고백 소재가 연속으로
    # 반복되지 않게 한다(select_episode 참고). recent_patterns_used와 동일한
    # 원리, 별도 풀이라 별도 필드로 추적한다.
    recent_episodes_used: list[str]

    # ── 스몰토크: 이름 직후 안부 힌트 ── 직전 턴에 preferred_name이 새로
    # 채워졌는지를 코드가 감지해서 다음 턴에만 True로 세팅한다. "방금 이름을
    # 알게 됐는지"를 LLM이 대화 이력을 훑어 추론하게 두면 대화가 길어질수록
    # 오판 가능성이 커지므로, 결정적으로 판단해서 SMALLTALK_NAME_GREETING_HINT
    # 주입 여부를 코드가 정한다. 힌트를 소비한 다음 턴엔 다시 False로 리셋.
    name_greeting_pending: bool

    # ── 스몰토크: 질문 연속 턴 카운터 ── reply에 물음표가 있었던 턴이 연속
    # 몇 번째인지 기록한다. 임계치(_MAX_CONSECUTIVE_QUESTION_TURNS)에 닿으면
    # 다음 턴엔 질문 없이 리액션만 하도록 프롬프트로 강제한다 — "질문 없는
    # 턴도 괜찮다"는 권장 문구만으로는 실측에서 매번 무시됐기 때문.
    consecutive_question_turns: int

    # ── 스몰토크: 이미 물었지만 아직 답을 못 들은 화제 ── 매 턴 LLM에게
    # 대화 전체를 다시 훑어서 중복 질문인지 판단하게 하는 대신, reply에
    # 어떤 화제 키워드가 있었는지 코드로 감지해서 여기 누적한다(해당
    # profile 필드가 채워지면 자동으로 빠진다). 토큰 절감 + 대화가 길어질
    # 때의 판단 정확도 개선이 목적.
    already_asked_topics: list[str]

    # ── 스몰토크: 화제 정체 턴 카운터 ── REQUIRED_FIELDS 진행이 없는 턴이
    # 연속 몇 번째인지 기록한다. 임계치(_TOPIC_STALL_TURN_THRESHOLD)에
    # 닿으면 다음 턴에 필드별 구체적 예시로 강제 화제 전환을 건다 —
    # "필수 항목을 우선 고려하라"는 추상 지시만으로는 "방금 나온 이야기에서
    # 파생되는 화제로 이어가라"는 더 강한 지시에 실측에서 매번 졌기 때문.
    turns_without_required_progress: int

    # ── 스몰토크: 건강 화제 후속 질문 강제 카운터 ── 당뇨/고혈압 등 의학적
    # 키워드가 사용자 발화에서 감지되면(detect_health_disclosure) 세워지고,
    # 이 값이 0보다 큰 동안은 check_completion_gate가 필수 필드 충족률과
    # 무관하게 온보딩 완료를 보류한다 — 건강 이슈는 안전과 직결돼서, 다른
    # 화제처럼 한 번 스치고 넘어가면 안 된다는 게 실측(당뇨 언급 직후 바로
    # 온보딩 종료)으로 확인됐기 때문.
    health_followup_turns_remaining: int

    # ── 스몰토크: 직전 봇 응답 원문 ── 최근 1~2턴의 reply를 그대로 저장해서,
    # 새 reply가 화제가 전혀 다른데도 이전 리액션 문구를 거의 그대로
    # 재사용하는지(check_reply_verbatim_reuse) 후처리로 감지한다 — 짧은
    # 맞장구("그래") 턴에서 이 현상이 실측으로 확인됐다.
    recent_replies: list[str]

# ══════════════════════════════════════════════
# 2. MemoryState
# ══════════════════════════════════════════════

class MemoryState(TypedDict):
    user_id: str
    user_profile: dict[str, Any]
    purchase_history: list[dict[str, Any]]
    preference_memory: dict[str, Any]
    collective_context: Optional[dict[str, Any]]
    conversation_summary: Optional[str]

# ══════════════════════════════════════════════
# 4. Bridge Functions
# ══════════════════════════════════════════════

def bridge_memory_to_shopping(memory: MemoryState) -> dict:
    return {"last_agent": "memory_agent"}


def get_default_shopping_state(user_id: str, session_id: str) -> dict:
    return {
        "messages": [],
        "stage": "idle",
        "intent": None,
        "last_agent": None,
        "error": None,
        "degraded_mode": False,
        "degradation_reason": None,
        "failure_stage": None,
        "ranking_mode": None,
        "source_used": None,
        "confidence": None,
        "immediate_response": None,
        "needs_clarification": False,
        "clarification_reason": None,
        "recommend_from_profile": False,
        "fallback_stuck_turns": 0,
        "keywords": [],
        "search_query": None,
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
        "recipe_dish": None,
        "recipe_people": None,
        "recipe_items": [],
        "current_recipe_item_index": 0,
        "recommendation_context": None,
        "reorder_resolution": None,
        "storage_state_path": None,
        "cart_items": [],
        "current_option_value": None,
        "address_text": None,
        "tool_calls": None,
        "tool_results": None,
        "conversation_summary": None,
        "order_id": None,
        "cart": None,
        "order": None,
        "payment": None,
        "checkout_session": None,
        "payment_idempotency_key": None,
        "onboarding_started_at": None,
        "recent_patterns_used": [],
        "recent_episodes_used": [],
        "name_greeting_pending": False,
        "consecutive_question_turns": 0,
        "already_asked_topics": [],
        "turns_without_required_progress": 0,
        "health_followup_turns_remaining": 0,
        "recent_replies": [],
    }
