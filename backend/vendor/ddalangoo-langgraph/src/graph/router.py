from datetime import datetime, timezone
from typing import Callable, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from configs.llm_config import get_llm
from src.agents.intent_agent import _BUY_TRIGGERS, _REORDER_SIGNALS
from src.state.schema import ShoppingState
from src.utils.agent_logger import agent_logger, _ptype

RouteName = Literal[
    "context_agent",
    "reorder_agent",
    "product_agent",
    "response_agent",
    "payment_agent",
    "recipe_agent",
    "purchase_queue_agent",
    "smalltalk_agent",
    "ask_what_to_buy",
    "respond",
    "cancel_confirmation",
    "cancel",
    "order_action_boundary",
    "fallback_orchestrator",
    "end",
]

# fallback_orchestrator를 절대 태우지 않는 stage — 결제는 human-in-the-loop이
# 필수인 영역이라 LLM에 자유도를 주지 않는다(설계 문서 2-2 참고).
_FALLBACK_EXCLUDED_STAGES = frozenset({"payment_processing", "payment_password_required"})

Decide = Callable[[RouteName], RouteName]

# stage별 서브라우터 시그니처를 통일한다 — 일부 함수는 state/pending_type을
# 안 쓰기도 하지만, 통일된 시그니처라야 _STAGE_ROUTERS를 dict dispatch로
# 단순하게 유지할 수 있다. 각 함수는 자기 stage 로직만 알면 되고, 다른
# stage 블록과 변수를 공유하지 않는다 (route() 하나에 다 있을 때보다
# 블록 간 결합이 낮다).


def _route_cart_shopping(state: ShoppingState, intent: str | None, pending_type: str, decide: Decide) -> RouteName:
    if intent in ("buy", "reorder", "refine", "compare_platforms"):
        if intent == "reorder":
            return decide("reorder_agent")
        return decide("product_agent")
    if pending_type == "what_to_buy":
        if intent == "reorder":
            return decide("reorder_agent")
        if intent in ("buy", "refine", "compare_platforms"):
            return decide("product_agent")
        if intent == "confirm":
            return decide("payment_agent")
        return decide("respond")
    if pending_type == "cart_review":
        if intent in ("confirm", "quantity_change"):
            return decide("payment_agent")
        if intent in ("deny", "cancel"):
            return decide("cancel")
        return decide("respond")
    if intent == "confirm":
        return decide("payment_agent")
    if intent in ("deny", "next"):
        return decide("ask_what_to_buy")
    return decide("respond")


def _route_product_confirming(state: ShoppingState, intent: str | None, pending_type: str, decide: Decide) -> RouteName:
    pa_type = (state.get("pending_action") or {}).get("type")

    if pa_type == "product_select":
        # unclear도 reorder_agent로 보낸다 — 후보 목록에 대한 자유 답변은
        # intent 분류가 원래 불안정하다(예: "음... 잘 모르겠어요"). reorder_agent의
        # _select_from_pending이 후보명과 직접 매칭을 시도하고, 실패해도
        # "번호로 다시 말씀해 주세요"처럼 맥락 있는 재질문을 하므로, 여기서
        # intent만 보고 generic respond로 넘기는 것보다 낫다(실측 확인).
        if intent in ("confirm", "option_select", "unclear"):
            return decide("reorder_agent")
        return decide("respond")

    if pa_type == "price_change_confirm":
        if intent in ("confirm", "deny", "cancel", "next"):
            return decide("payment_agent")
        return decide("respond")

    if intent == "confirm":
        if not state.get("quantity"):
            return decide("respond")
        return decide("payment_agent")

    # LLM이 수량 변경을 quantity_change로 분류했지만 실제로는 구매 확정 수량 입력
    if intent == "quantity_change" and state.get("quantity"):
        return decide("payment_agent")

    if intent in ("buy", "reorder"):
        if intent == "reorder":
            return decide("reorder_agent")
        return decide("product_agent")

    if intent in ("deny", "next"):
        return decide("product_agent")

    if intent == "ask":
        return decide("response_agent")

    if intent in ("refine", "compare_platforms"):
        return decide("product_agent")

    return decide("respond")


def _route_searching(state: ShoppingState, intent: str | None, pending_type: str, decide: Decide) -> RouteName:
    if intent in ("refine", "compare_platforms"):
        return decide("product_agent")
    if intent == "ask":
        return decide("response_agent")
    return decide("respond")


def _route_recipe_planning(state: ShoppingState, intent: str | None, pending_type: str, decide: Decide) -> RouteName:
    if pending_type == "ingredient_confirm":
        # confirm(Mode 3: 현재 품목 쇼핑 시작)은 purchase_queue_agent로 —
        # recipe_agent는 이제 재료 추론(Mode 1)/편집(Mode 2)만 담당한다(Unit 2).
        if intent == "confirm":
            return decide("purchase_queue_agent")
        if intent in ("deny", "refine"):
            return decide("recipe_agent")
    return decide("respond")


_STAGE_ROUTERS: dict[str, Callable[[ShoppingState, str | None, str, Decide], RouteName]] = {
    "cart_shopping": _route_cart_shopping,
    "product_confirming": _route_product_confirming,
    "searching": _route_searching,
    "recipe_planning": _route_recipe_planning,
}

# idle 등 stage별 서브라우터가 없을 때의 기본 매핑
_DEFAULT_ROUTING_MAP: dict[str, RouteName] = {
    "buy": "context_agent",
    "reorder": "reorder_agent",
    "compare_platforms": "product_agent",
    "refine": "product_agent",
    "ask": "response_agent",
    # WON-23 Unit 2 — 상품을 정하기 전 조언 요청은 카탈로그 검색을 안 거친다
    # (product_agent 미호출). response_agent가 이미 "카탈로그 없이 텍스트만
    # 생성"하는 유일한 노드라 새 경량 노드를 안 만들고 여기 재사용한다(응답
    # 생성 로직 자체는 Unit 3, 지금은 placeholder).
    "product_decision_advice": "response_agent",
    "next": "product_agent",
    "confirm": "respond",
    "deny": "respond",
    "option_select": "respond",
    "quantity_change": "respond",
    "address_change": "respond",
}


def _extract_last_user_text(state: ShoppingState) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", "")
    return ""


# WON-36 — 확정 후/idle 취소·환불 발화. DDALANGOO 는 third-party 주문 취소/환불
# 수단이 없어 확답 불가 영역 → fallback_orchestrator 자유생성 전에 가로챈다.
# "무르다/물러줘"(반품 구어) 는 오탐 위험("사과 물러요")이 있어 "반품"으로만 커버.
_ORDER_CANCEL_REFUND_TERMS = ("취소", "환불", "반품")


def _mentions_order_cancel_refund(text: str) -> bool:
    return bool(text) and any(t in text for t in _ORDER_CANCEL_REFUND_TERMS)


def _looks_like_order_request_fallback(text: str) -> bool:
    """_classify_order_request의 LLM 호출이 실패했을 때만 쓰는 최후 폴백.
    intent_agent가 사후 교정에 쓰는 트리거 세트(_BUY_TRIGGERS/_REORDER_SIGNALS)를
    재사용한 순수 키워드 매칭 — "계란 있어?"처럼 트리거 단어가 없는 명확한
    요청은 못 잡지만, LLM 호출 자체가 죽었을 때 아예 판단을 못 하는 것보다는 낫다."""
    return any(t in text for t in _BUY_TRIGGERS) or any(t in text for t in _REORDER_SIGNALS)


class _OrderRequestCheck(BaseModel):
    is_order_request: bool = Field(
        description="이 발화가 상품 구매/조회 등 명확한 쇼핑 요청이면 true, "
        "인사·잡담·일상 대화면 false. 애매하면 false."
    )


_ORDER_GATE_PROMPT = """\
아래 사용자 발화 하나만 보고 판단하세요: 이게 상품 구매/조회 등 쇼핑 관련
명확한 요청인가요, 아니면 인사/잡담/일상 대화인가요?

명확한 요청의 예: "우유 사줘", "계란 있어?", "딸기 얼마예요?", "저번에 산 거
다시 주문해줘", "사과 좀 찾아줘"
잡담의 예: "안녕하세요", "요즘 소화가 잘 안돼요", "혼자 살아요", "몰라", "ㅇㅇ"

애매하면 잡담(false)으로 판단하세요 — 확신 없이 요청으로 잘못 판단하면
온보딩 대화가 너무 빨리 끊깁니다.

발화: {text}
"""

_order_gate_llm: BaseChatModel | None = None


def _get_order_gate_llm() -> BaseChatModel:
    global _order_gate_llm
    if _order_gate_llm is None:
        # "context" 모델 슬롯 재사용 — smalltalk_agent와 동일한 저비용 모델
        # 티어라, route_entry 전용 새 환경변수를 따로 안 늘려도 된다.
        _order_gate_llm = get_llm("context", temperature=0, max_tokens=20, retry_owner="application")
    return _order_gate_llm


def _classify_order_request(text: str) -> bool:
    """route_entry 전용 경량 이진 분류 — intent_agent의 14-way 분류/슬롯
    추출과는 완전히 분리된, 훨씬 단순하고 값싼 별도 LLM 호출이다("intent가
    관여 안 함" 원칙은 그대로 유지). LLM 호출이 실패하면 키워드 휴리스틱으로
    폴백한다."""
    if not text:
        return False
    try:
        structured = _get_order_gate_llm().with_structured_output(_OrderRequestCheck, method="json_schema")
        result = structured.invoke([HumanMessage(content=_ORDER_GATE_PROMPT.format(text=text))])
        if not isinstance(result, _OrderRequestCheck):
            raise ValueError("structured output 파싱 실패")
        return result.is_order_request
    except Exception as e:
        agent_logger.log(f"[route_entry] 주문요청 판단 LLM 실패, 키워드 폴백: {e}")
        return _looks_like_order_request_fallback(text)


def route_entry(state: ShoppingState) -> Literal["smalltalk_agent", "intent_agent"]:
    """
    온보딩 미완료 신규유저는 intent_agent를 거치지 않고 바로 smalltalk_agent로
    보낸다 — smalltalk 트리거는 LLM의 intent 분류 대상이 아니라, 코드가 결정적으로
    판단하는 온보딩 이벤트다(intent_agent가 매 턴 "이거 잡담인가?"를 판단하지 않는다).

    "이미 온보딩됨" 판정은 두 신호의 OR:
    - profile.onboarded_at: smalltalk_agent가 온보딩을 완료(onboarding_complete=true)
      하면 찍는 플래그.
    - 구매이력 존재: onboarded_at 플래그가 생기기 전부터 이미 구매 이력이 있던
      기존 유저를 신규유저로 오판하지 않기 위한 하위호환 신호.

    예외: 위 조건상 아직 온보딩 중이라도, 이번 발화가 _classify_order_request로
    명확한 쇼핑 요청("우유 사줘"뿐 아니라 "계란 있어?" 같은 질문형도 포함)이라고
    판단되면 smalltalk을 건너뛰고 바로 intent_agent로 보낸다. smalltalk_agent를
    거치면 확인 질문만 하고 onboarding_complete=true로 끝내는데, 이때 실제
    요청 키워드("된장찌개 재료" 등)는 어디에도 안 남아서 다음 턴엔 "네" 같은
    짧은 답만 남고 원래 요청이 사라지는 문제가 실측 테스트로 확인됐다 —
    그래서 이 경우엔 아예 그 턴에 intent_agent가 원문 그대로 받아 처리하게
    한다. 이미 쇼핑 의사를 명확히 보였으므로 온보딩도 여기서 끝난 걸로 보고
    onboarded_at을 남긴다(안 그러면 다음 idle 턴에 다시 온보딩 게이트에 걸린다).

    이 판단은 키워드 매칭이 아니라 경량 LLM 분류다(_classify_order_request) —
    "우유 사줘"류 트리거 단어가 없는 "계란 있어?", "딸기 얼마예요?" 같은
    질문형 요청도 잡아야 해서, 순수 키워드 매칭만으로는 재현율이 부족했다.
    다만 intent_agent의 14-way 분류/슬롯 추출과는 완전히 별개의, 훨씬 단순한
    이진 분류 호출이라 "intent가 온보딩에 관여하지 않는다"는 원칙은 그대로
    유지된다.
    """
    if state.get("stage", "idle") != "idle":
        return "intent_agent"
    user_id = state.get("user_id", "")
    if not user_id:
        return "intent_agent"
    from src.tools import db_client
    profile = db_client.get_profile(user_id)
    already_onboarded = bool(profile and profile.get("onboarded_at"))
    has_purchase_history = bool(db_client.get_purchase_histories(user_id))
    if already_onboarded or has_purchase_history:
        return "intent_agent"

    if _classify_order_request(_extract_last_user_text(state)):
        merged = dict(profile or {})
        merged["onboarded_at"] = datetime.now(timezone.utc).isoformat()
        db_client.save_profile(user_id, merged)
        return "intent_agent"

    return "smalltalk_agent"


def route_session_start(state: ShoppingState) -> Literal["smalltalk_agent", "entry_engagement", "wait_for_input"]:
    """세션을 열자마자 딸랑구가 먼저 말을 걸지 결정한다(그래프 진입점,
    session_start 노드의 조건부 분기).

    아직 대화 메시지가 없는 최초 진입에서: 신규·미온보딩 사용자는
    smalltalk_agent로 보내 선제 인사를 하게 하고, 이미 온보딩됐거나 구매
    이력이 있는 사용자는 entry_engagement로 보낸다(만족도 체크인/프로필
    이어 묻기/그마저 없으면 "오늘은 뭘 사고 싶으세요?" — entry_engagement_node
    가 항상 뭔가 말할 게 있으므로 여기서 "물어볼 게 있을 때만" 같은 조건을
    따로 안 둔다). 사용자 메시지가 이미 담긴 상태로 그래프를 시작하는
    테스트/외부 호출은 선제 인사를 끼워 넣지 않고 기존 입력 대기 흐름을
    그대로 쓴다 — 이 분기는 "메시지가 정말 하나도 없는 최초 진입"만
    노린다(route_entry는 매 idle 턴마다 온보딩 여부를 재판단하지만, 이
    함수는 세션이 열리는 그 순간에만 한 번 쓰인다).
    """
    if state.get("messages"):
        return "wait_for_input"
    if state.get("stage", "idle") != "idle":
        return "wait_for_input"
    user_id = state.get("user_id", "")
    if not user_id:
        return "wait_for_input"

    from src.tools import db_client

    profile = db_client.get_profile(user_id)
    already_onboarded = bool(profile and profile.get("onboarded_at"))
    has_purchase_history = bool(db_client.get_purchase_histories(user_id))
    return "entry_engagement" if (already_onboarded or has_purchase_history) else "smalltalk_agent"


def route(state: ShoppingState) -> RouteName:
    """
    Intent + Stage 기반 라우팅.
    1. clarification 우선
    2. cancel 우선
    3. payment_processing이면 Payment로 위임
    4. stage별 서브라우터(_STAGE_ROUTERS)로 위임
    5. 해당 없으면 idle 기본 매핑(_DEFAULT_ROUTING_MAP)
    """
    intent = state.get("intent")
    stage = state.get("stage", "idle")
    confidence = state.get("confidence") or 0.0
    needs_clarification = state.get("needs_clarification", False)
    pending_type = _ptype(state.get("pending_action"))

    def _decide(dest: RouteName) -> RouteName:
        agent_logger.log_router("intent_agent", dest, intent or "-", stage, pending_type)
        return dest

    # WON-36 — idle(주문 확정 후 다음 턴 포함)에서 취소·환불 발화는 다른 어떤
    # 분기보다 먼저 deterministic 하게 가로챈다. DDALANGOO 는 third-party 주문의
    # 취소·환불을 조회·실행할 수단이 없어, fallback_orchestrator 자유생성이나
    # 쇼핑 세션 중단(cancel_confirmation) 문구로 새면 근거 없는 확답/오정보가
    # 나간다(고령층 결제 발화라 리스크 큼). completed/failed 는 after_respond()가
    # END 로 끝내 route()에 도달하지 않으므로 idle 만 본다.
    # 예외: cancel_confirm 대기 중의 답변("취소"/"네")은 쇼핑 중단 확정이므로 제외.
    if (
        stage == "idle"
        and pending_type != "cancel_confirm"
        and _mentions_order_cancel_refund(_extract_last_user_text(state))
    ):
        return _decide("order_action_boundary")

    # 만족도 체크인/프로필 이어 묻기 진행 중(pending_action.payload.
    # satisfaction_check 또는 profile_topup)이면 needs_clarification/confidence/
    # stuck_turns 판단과 무관하게 항상 fallback_orchestrator로 보내 답변을
    # 마저 처리한다 — product_select가 payload 기반으로 결정적으로 예외
    # 처리되는 것과 같은 패턴(LLM 추측 없음, src/agents/satisfaction_checkin.py,
    # src/agents/profile_topup.py 참고).
    if pending_type == "clarification":
        _payload = (state.get("pending_action") or {}).get("payload") or {}
        if _payload.get("satisfaction_check") or _payload.get("profile_topup"):
            return _decide("fallback_orchestrator")

    # 전체 삭제는 파괴적 동작이므로 취소 확인 응답을 일반 confidence/fallback
    # 판정보다 먼저 처리한다. 모호한 답은 실행하지 않고 확인 문구를 반복한다.
    if pending_type == "cancel_confirm":
        if intent in ("confirm", "cancel") and not needs_clarification:
            return _decide("cancel")
        if intent == "deny" and not needs_clarification:
            return _decide("cancel_confirmation")
        return _decide("respond")

    # reorder는 예외 — needs_clarification=true라도 respond로 바로 보내지 않고
    # reorder_agent(아래 stage-router/기본 매핑에서 도달)로 보낸다. reorder_agent가
    # 정확히 "상품명 없는 모호한 재구매"를 처리하도록 설계돼 있어서(구매이력 조회 →
    # 후보 나열/되묻기), 여기서 막으면 그 분기를 탈 기회 자체가 없어져 구매이력을
    # 전혀 모르는 맥락 없는 되물음만 반복된다(routing-2026-08-18-001로 재현 확인됨).
    #
    # pending_action.type == "product_select"도 예외 — 이미 후보 목록을 나열해
    # 되묻는 중인데, 사용자의 후속 답변이 애매(unclear)하다고 여기서 respond로
    # 보내버리면 reorder_agent 자체의 재질문 로직(_select_from_pending이 후보와
    # 매칭 시도, 실패하면 "번호로 다시 말씀해 주세요")을 탈 기회가 아예 없어져
    # 맥락 없는 일반 clarification만 반복된다(실측 확인, fl-2026-08-20-001).
    if (
        (needs_clarification or confidence < 0.5 or intent == "unclear")
        and intent != "reorder"
        and pending_type != "product_select"
    ):
        # Stuck Trigger: 정해진 재질문을 이미 한 번 거치고도(fallback_stuck_turns>=1)
        # 또 막히면, respond로 같은 재질문을 반복하는 대신 fallback_orchestrator가
        # 더 넓은 맥락으로 진단하게 한다. 결제 관련 stage는 절대 대상이 아니다
        # (human-in-the-loop 경계, 설계 문서 참고). 1차 시도는 항상 지금처럼
        # deterministic 재질문 그대로 나간다.
        stuck_turns = state.get("fallback_stuck_turns") or 0
        if stuck_turns >= 1 and stage not in _FALLBACK_EXCLUDED_STAGES:
            return _decide("fallback_orchestrator")
        return _decide("respond")

    if intent == "cancel":
        return _decide("cancel_confirmation")

    if stage == "payment_processing":
        return _decide("payment_agent")

    if stage_router := _STAGE_ROUTERS.get(stage):
        return stage_router(state, intent, pending_type, _decide)

    # buy + recipe_dish (아직 재료 목록 없음) → recipe_agent
    if intent == "buy" and state.get("recipe_dish") and not state.get("queue_items"):
        return _decide("recipe_agent")

    return _decide(_DEFAULT_ROUTING_MAP.get(intent, "respond"))


def after_product_agent(state: ShoppingState) -> Literal["response_agent", "respond"]:
    if state.get("error") in ("invalid_keywords", "no_candidates", "no_relevant_products", "no_more_products"):
        return "respond"
    return "response_agent"


def after_response_agent(state: ShoppingState) -> Literal["respond"]:
    return "respond"


def after_reorder_agent(state: ShoppingState) -> Literal["respond", "product_agent"]:
    if state.get("error") == "reorder_no_match":
        return "product_agent"
    return "respond"


def after_context_agent(state: ShoppingState) -> Literal["product_agent", "respond"]:
    stage = state.get("stage")
    if stage == "completed":
        return "respond"
    intent = state.get("intent")
    pending_type = _ptype(state.get("pending_action"))
    dest = "product_agent" if intent in ("buy", "refine", "compare_platforms") else "respond"
    agent_logger.log_router("context_agent", dest, intent or "-", stage or "-", pending_type)
    return dest


def after_recipe_agent(state: ShoppingState) -> Literal["context_agent", "respond"]:
    stage = state.get("stage")
    intent = state.get("intent") or "-"
    pending_type = _ptype(state.get("pending_action"))

    def _decide(dest):
        agent_logger.log_router("recipe_agent", dest, intent, stage or "-", pending_type)
        return dest

    # Mode 3/4는 purchase_queue_agent로 이동했다(Unit 2) — recipe_agent는 이제
    # Mode 1/2(재료 추론/편집)만 담당하고 항상 stage="recipe_planning"으로 끝나
    # stage=="idle" 분기는 이제 도달하지 않는다(정리는 Unit 3에서).
    if stage == "idle":
        return _decide("context_agent")
    return _decide("respond")


def after_purchase_queue_agent(state: ShoppingState) -> Literal["context_agent", "respond"]:
    """recipe_agent의 옛 Mode 3/4 출력 라우팅과 동일한 로직 — Mode 3(현재 품목
    쇼핑 시작)는 stage="idle"로 끝나 context_agent로, Mode 4(다음 품목 안내/완료)는
    stage="recipe_planning"/"cart_shopping"으로 끝나 respond로."""
    stage = state.get("stage")
    intent = state.get("intent") or "-"
    pending_type = _ptype(state.get("pending_action"))

    def _decide(dest):
        agent_logger.log_router("purchase_queue_agent", dest, intent, stage or "-", pending_type)
        return dest

    if stage == "idle":
        return _decide("context_agent")
    return _decide("respond")


def after_payment_agent(state: ShoppingState) -> Literal["context_agent", "purchase_queue_agent", "respond"]:
    stage = state.get("stage", "idle")
    pending_type = _ptype(state.get("pending_action"))
    intent = state.get("intent") or "-"

    def _decide(dest):
        agent_logger.log_router("payment_agent", dest, intent, stage, pending_type)
        return dest

    if stage == "completed":
        return _decide("context_agent")

    # cart_review에서 비우기/조작 처리 중 검색된 적 없는 신규 품목을 발견하면
    # (예: "싹 다 비우고 계란/참기름만 담아") payment_agent가 stage=idle,
    # intent=buy로 곧장 첫 품목 검색을 시작하도록 세팅한다 — 일반 buy 요청과
    # 동일하게 context_agent로 보낸다(fl-2026-08-25-001 잔여 케이스).
    if stage == "idle" and intent == "buy":
        return _decide("context_agent")

    # 품목 큐 모드(레시피/다중구매 공용): 장바구니 담기 후 다음 품목으로 자동 진행
    if stage == "cart_shopping" and pending_type == "continue_shopping":
        queue_items = state.get("queue_items") or []
        idx = state.get("current_queue_index") or 0
        if queue_items and idx <= len(queue_items) - 1:
            return _decide("purchase_queue_agent")

    return _decide("respond")


def after_fallback_orchestrator(state: ShoppingState) -> RouteName:
    """fallback_orchestrator_node 실행 후 라우팅.

    action="clarify"/"chat"이었으면 fallback_orchestrator가 pending_action.type을
    "clarification"으로 세팅해뒀으므로 곧장 respond로 보낸다. action="recover"였으면
    fallback_orchestrator가 intent/keywords 등을 정상 슬롯 값으로 고쳐놨을 뿐이므로,
    새 라우팅 로직을 만들지 않고 route() 함수를 그대로 재호출한다 — route()는
    이제 정상적으로 fallback_stuck_turns=0이고 needs_clarification=False인 state를
    보고, 마치 intent_agent가 원래 이 값을 냈던 것처럼 평소와 동일하게 판단한다."""
    pending_type = _ptype(state.get("pending_action"))
    if pending_type == "clarification":
        return "respond"
    return route(state)


def after_respond(state: ShoppingState) -> Literal["wait_for_input", "end"]:
    stage = state.get("stage", "idle")
    error = state.get("error")

    if stage in ("completed", "failed"):
        return "end"

    if error and "fatal" in error.lower():
        return "end"

    return "wait_for_input"
