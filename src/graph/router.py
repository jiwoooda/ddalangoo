from typing import Callable, Literal
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

    if pa_type == "quantity_confirm":
        if state.get("quantity"):
            return decide("payment_agent")
        return decide("respond")

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
    "smalltalk": "smalltalk_agent",
}


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
