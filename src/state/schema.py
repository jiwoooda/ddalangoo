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
    # WON-23 Unit 1 — 아직 상품을 정하기 전, "어떤 게 나을지" 조언을 구하는
    # 발화("사과랑 딸기 중 뭐가 나아?", "이 계절엔 뭐가 맛있어?"). ask(이미
    # 고른 상품에 대한 질문)와는 대상이 다르고, next(다른 후보 요청, 진행
    # 중인 검색이 있어야 함)와도 다르다 — 카탈로그 접근 없이 조언만 생성
    # (분류·라우팅은 Unit 2/3, 이번 Unit은 분류값만 추가).
    "product_decision_advice",
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
    "cancel_confirm",
    "cancel_declined",
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
    "substitution_confirm",
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
    # WON-38 Unit 2 — 결제 흐름 질문의 (topic, type). intent_agent가 매 턴
    # classify_payment_question()으로 다시 쓴다(quantity/needs_clarification과 동일
    # 패턴). payment_agent/response_agent가 intent=="ask" 게이트 안에서만 소비하고,
    # 라우팅 목적지 결정에는 개입하지 않는다.
    question_classification: Optional[dict[str, Any]]
    # WON-20 Unit 2 — 발화 scope 판단(src/utils/scope_classifier.classify_scope).
    # intent_agent가 매 턴 다시 쓴다(question_classification과 동일 패턴). scope가
    # "out_of_scope"(고신뢰: 가전 제어·전화·법률/금융 상담 등)면 intent_agent가
    # 1턴째부터 "어떤 상품을 찾으세요?" 되물음 대신 정중한 범위 안내로 바꾼다 —
    # 라우팅 목적지 자체는 안 바꾼다. goal_shift는 Unit 3(fallback_orchestrator)가 소비.
    scope: Optional[str]  # "in_scope" | "bridgeable" | "out_of_scope" | None
    goal_shift: bool
    # "아무거나 사주세요"처럼 상품명 없이 dismissive하게 답할 때, 되묻는 대신
    # 프로필의 favorite_foods로 대신 채우라는 intent_agent → context_agent 신호.
    # intent_agent가 매 턴 명시적으로 True/False를 다시 쓴다(과거 턴 값이 이번
    # 턴에 새어들지 않도록) — quantity/needs_clarification과 동일한 패턴.
    recommend_from_profile: bool

    # 장바구니에 대한 조작들(순서대로 적용). 품목별로 다른 add/remove/수량조작이
    # 섞인 복합 요청("딸기는 하나 더하고 우유는 2개 뺄게")이나, 장바구니를 통째로/
    # 부분적으로 비우는 요청("다 빼고 X만" = [CLEAR_CART, SET_QUANTITY(X,...)])을
    # 표현한다. recommend_from_profile과 동일하게 intent_agent가 매 턴 명시적으로
    # 다시 쓴다 — payment_agent가 그 턴에만 소비한다.
    cart_operations: list[dict[str, Any]]

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

    # ── ProductRequest(WON-22 Unit 1) ── keywords 하나로는 "카테고리 검색"과
    # "정확한 제품 지정"을 구분 못 해서(product_agent._matches_requested_keywords가
    # keywords 중 하나만 일치해도 통과시키는 근본 원인) src/state/product_request.py의
    # ProductRequest를 구조화 계약으로 도입한다. 지금은 계약만 존재 — 아무도
    # 안 채우고(Unit 2가 intent_agent에서 채움) 안 읽는다(Unit 4+가 product_agent
    # 에서 소비함). keywords 기반 기존 검색/랭킹은 이번 Unit에서 그대로 유지된다.
    # ProductRequest.model_dump()한 plain dict로 저장(state는 Pydantic 인스턴스를
    # 직접 들고 있지 않음 — 체크포인터 직렬화 때문).
    product_request: Optional[dict[str, Any]]

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

    # ── 품목 큐(purchase_queue_agent) ── recipe_agent의 Mode 3/4 루프를
    # recipe_dish에 의존하지 않는 범용 실행기로 분리한 필드(recipe_items/
    # current_recipe_item_index는 Unit 3에서 완전히 은퇴 — 아무도 안 읽던
    # current_recipe_item_index와, 여기 queue_items로 대체 가능했던
    # recipe_items를 두 벌 유지할 이유가 없었다). queue_source는 이 큐를
    # 채운 쪽("recipe"/"multi_buy")을 명시해 — purchase_queue_agent는
    # recipe_dish를 절대 참조하지 않고 이 값만으로 문구를 고른다.
    queue_items: list[dict[str, Any]]
    current_queue_index: int
    queue_source: Optional[Literal["recipe", "multi_buy"]]
    # "싹 다 비우고 계란만 담아"처럼 buy 발화에 CLEAR_CART가 섞였을 때 intent_agent가
    # 세운다 — cart_operations(매 턴 리셋)와 달리 payment_agent Step 0가 실제로
    # 담기를 실행하는 턴(보통 확인 턴 몇 턴 뒤)까지 살아있어야 해서 queue_items와
    # 같은 패턴으로 턴을 넘어 지속시킨다. Step 0가 소비한 뒤 False로 되돌린다.
    queue_clear_existing: bool

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
        "question_classification": None,
        "scope": None,
        "goal_shift": False,
        "recommend_from_profile": False,
        "cart_operations": [],
        "fallback_stuck_turns": 0,
        "keywords": [],
        "search_query": None,
        "exclude_keywords": [],
        "negative_constraints": [],
        "quantity": None,
        "condition": None,
        "product_request": None,
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
        "queue_items": [],
        "current_queue_index": 0,
        "queue_source": None,
        "queue_clear_existing": False,
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


# ══════════════════════════════════════════════
# 5. Reset field-sets (WON-37 Unit 1)
# ══════════════════════════════════════════════
# cancel_node / ask_what_to_buy_node / fallback_orchestrator._recover_result /
# reset_turn_observability_node 가 각자 다른 필드 목록으로 "상태 초기화"를
# 손코딩해, 한 곳만 고쳐도 다른 지점은 불완전하게 남던 문제(WON-37)의 공통
# 기반. 이 유닛은 목록만 정의한다 — 아직 어떤 노드도 이 함수를 호출하지 않는다
# (Unit 2~4 에서 배선).
#
# 원칙:
# - 초기화 값은 전부 get_default_shopping_state() 의 기본값과 일치한다.
# - 헬퍼는 매 호출마다 새 list/dict 를 만들어 반환한다(공유 기본값 오염 방지).
# - stage / intent / error / last_agent / confidence / needs_clarification /
#   fallback_stuck_turns / 세션 식별자 등 "매 호출마다 상황별 값을 노드가 직접
#   지정하는" 플로우 제어 필드는 어느 셋에도 넣지 않는다 — 그건 초기화가
#   아니라 그 노드의 결정이다.
# - 네 카테고리는 서로 겹치지 않는다(각 필드는 정확히 한 셋에만).

# ── 상품 탐색 문맥 ── 검색어/조건/후보/선택상품/플랫폼 흔적.
PRODUCT_CONTEXT_RESET_FIELDS: tuple[str, ...] = (
    "keywords",
    "search_query",
    "exclude_keywords",
    "negative_constraints",
    "quantity",
    "condition",
    "product_request",
    "override_platform",
    "target_platforms",
    "tried_platforms",
    "selected_platform",
    "search_results",
    "scored_products",
    "recommended_products",
    "current_product_index",
    "selected_product",
    "product_url",
    "explanation",
    "highlight_specs",
)

# ── 구매/결제 플로우 ── 대기 액션 / 결제 멱등키 / 품목 큐 / 레시피 / 추천·재구매
# 해소 컨텍스트 / 장바구니 조작 파싱 결과.
PURCHASE_FLOW_RESET_FIELDS: tuple[str, ...] = (
    "pending_action",
    "payment_idempotency_key",
    "queue_items",
    "current_queue_index",
    "queue_source",
    "queue_clear_existing",
    "cart_operations",
    "recipe_dish",
    "recipe_people",
    "recommendation_context",
    "reorder_resolution",
)

# ── 실제 장바구니 삭제 ── state 필드는 cart_items 하나뿐이지만, mock 장바구니는
# state 밖(mock_tools 의 프로세스 저장소)에 있어서 이 셋만으로는 안 비워진다.
# schema 는 tools 계층을 import 하지 않으므로, "호출부가 mock_clear_cart(user_id)
# 도 함께 불러야 한다"는 계약을 아래 플래그로 표시한다.
CART_CLEAR_FIELDS: tuple[str, ...] = ("cart_items",)
CART_CLEAR_REQUIRES_MOCK_CLEAR_CART: bool = True

# ── 턴 관측값 ── reset_turn_observability_node(nodes.py)가 매 턴 초기화하는 5개.
TURN_OBSERVABILITY_RESET_FIELDS: tuple[str, ...] = (
    "degraded_mode",
    "degradation_reason",
    "failure_stage",
    "ranking_mode",
    "source_used",
)


def product_context_reset() -> dict[str, Any]:
    """상품 탐색 문맥 초기화 — {필드명: 초기화값} 을 새로 만들어 반환."""
    return {
        "keywords": [],
        "search_query": None,
        "exclude_keywords": [],
        "negative_constraints": [],
        "quantity": None,
        "condition": None,
        "product_request": None,
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
    }


def purchase_flow_reset() -> dict[str, Any]:
    """구매/결제 플로우 초기화 — {필드명: 초기화값} 을 새로 만들어 반환."""
    return {
        "pending_action": None,
        "payment_idempotency_key": None,
        "queue_items": [],
        "current_queue_index": 0,
        "queue_source": None,
        "queue_clear_existing": False,
        "cart_operations": [],
        "recipe_dish": None,
        "recipe_people": None,
        "recommendation_context": None,
        "reorder_resolution": None,
    }


def cart_clear() -> dict[str, Any]:
    """장바구니 삭제의 state 부분 — {"cart_items": []}. 호출부는
    CART_CLEAR_REQUIRES_MOCK_CLEAR_CART 계약대로 mock_clear_cart(user_id) 도
    함께 호출해야 한다."""
    return {"cart_items": []}


def turn_observability_reset() -> dict[str, Any]:
    """턴 관측값 초기화 — {필드명: 초기화값} 을 새로 만들어 반환."""
    return {
        "degraded_mode": False,
        "degradation_reason": None,
        "failure_stage": None,
        "ranking_mode": None,
        "source_used": None,
    }
