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
    "smalltalk_agent",
    "ask_what_to_buy",
    "respond",
    "cancel",
    "end",
]

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
        if intent in ("confirm", "option_select"):
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
        if intent in ("confirm", "deny", "refine"):
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

    if needs_clarification or confidence < 0.5 or intent == "unclear":
        return _decide("respond")

    if intent == "cancel":
        return _decide("cancel")

    if stage == "payment_processing":
        return _decide("payment_agent")

    if stage_router := _STAGE_ROUTERS.get(stage):
        return stage_router(state, intent, pending_type, _decide)

    # buy + recipe_dish (아직 recipe_items 없음) → recipe_agent
    if intent == "buy" and state.get("recipe_dish") and not state.get("recipe_items"):
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

    # Mode 3: stage=idle → 재료 하나 쇼핑 시작 → context_agent
    if stage == "idle":
        return _decide("context_agent")
    # Mode 1/2/4: recipe_planning or cart_shopping → respond (메시지 표시)
    return _decide("respond")


def after_payment_agent(state: ShoppingState) -> Literal["context_agent", "recipe_agent", "respond"]:
    stage = state.get("stage", "idle")
    pending_type = _ptype(state.get("pending_action"))
    intent = state.get("intent") or "-"

    def _decide(dest):
        agent_logger.log_router("payment_agent", dest, intent, stage, pending_type)
        return dest

    if stage == "completed":
        return _decide("context_agent")

    # 레시피 모드: 장바구니 담기 후 다음 재료로 자동 진행
    if stage == "cart_shopping" and pending_type == "continue_shopping":
        recipe_items = state.get("recipe_items") or []
        idx = state.get("current_recipe_item_index") or 0
        if recipe_items and idx <= len(recipe_items) - 1:
            return _decide("recipe_agent")

    return _decide("respond")


def after_respond(state: ShoppingState) -> Literal["wait_for_input", "end"]:
    stage = state.get("stage", "idle")
    error = state.get("error")

    if stage in ("completed", "failed"):
        return "end"

    if error and "fatal" in error.lower():
        return "end"

    return "wait_for_input"
