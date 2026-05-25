from typing import Literal
from src.state.schema import ShoppingState
from src.utils.agent_logger import agent_logger, _ptype

RouteName = Literal[
    "memory_agent",
    "reorder_node",
    "platform_agent",
    "product_agent",
    "payment_agent",
    "quantity_check",
    "ask_what_to_buy",
    "respond",
    "cancel",
    "end",
]


def route(state: ShoppingState) -> RouteName:
    """
    Intent + Stage 기반 라우팅.
    원칙:
    1. clarification 우선
    2. cancel 우선
    3. payment_processing이면 Payment Subgraph로 위임
    4. product_confirming에서는 intent별 분기
    5. idle/searching에서는 intent 기반 분기
    """
    intent = state.get("intent")
    stage = state.get("stage", "idle")
    confidence = state.get("confidence") or 0.0
    needs_clarification = state.get("needs_clarification", False)
    pending_type = _ptype(state.get("pending_action"))

    def _decide(dest: RouteName) -> RouteName:
        agent_logger.log_router("intent_agent", dest, intent or "-", stage, pending_type)
        return dest

    # ── 1. 명확성 검사 ──
    if needs_clarification or confidence < 0.5 or intent == "unclear":
        return _decide("respond")

    # ── 2. cancel은 어디서든 cancel_node로 ──
    if intent == "cancel":
        return _decide("cancel")

    # ── 3. 결제 진행 중이면 Payment Subgraph가 처리 ──
    if stage == "payment_processing":
        return _decide("payment_agent")

    # ── 4. 장바구니 담긴 후 추가 쇼핑 여부 ──
    if stage == "cart_shopping":
        if intent == "confirm":
            return _decide("payment_agent")
        # 사용자가 무엇을 살지 이미 지정한 경우 → 바로 검색/재구매 흐름
        if pending_type == "what_to_buy":
            if intent == "reorder":
                return _decide("memory_agent")
            if intent in ("buy", "refine", "compare_platforms"):
                return _decide("platform_agent")
            return _decide("respond")
        # '다른것도 살래' 등 상품 미지정 → 무엇을 살지 먼저 질문
        if intent in ("deny", "next"):
            return _decide("ask_what_to_buy")
        # 상품명을 직접 말한 경우 (예: "우유 살래") → 바로 검색
        if intent in ("buy", "reorder", "refine", "compare_platforms"):
            if intent == "reorder":
                return _decide("memory_agent")
            return _decide("platform_agent")
        return _decide("respond")

    # ── 5. 상품 확인 단계 ──
    if stage == "product_confirming":
        pa_type = (state.get("pending_action") or {}).get("type")

        if pa_type == "quantity_confirm":
            if state.get("quantity"):
                return _decide("payment_agent")
            if intent in ("confirm", "quantity_change"):
                return _decide("quantity_check")

        if pa_type == "product_select":
            if intent in ("confirm", "option_select"):
                return _decide("reorder_node")
            return _decide("respond")

        if pa_type == "platform_suggest":
            if intent in ("confirm", "deny", "next"):
                return _decide("platform_agent")

        if pa_type == "price_change_confirm":
            if intent in ("confirm", "deny", "cancel", "next"):
                return _decide("payment_agent")
            return _decide("respond")

        if intent == "confirm":
            if not state.get("quantity"):
                return _decide("quantity_check")
            return _decide("payment_agent")

        if intent in ("deny", "next", "ask"):
            return _decide("product_agent")

        if intent in ("refine", "compare_platforms"):
            return _decide("platform_agent")

        return _decide("respond")

    # ── 6. 검색 중 ──
    if stage == "searching":
        if intent in ("refine", "compare_platforms"):
            return _decide("platform_agent")
        return _decide("respond")

    # ── 7. idle / 기본 Intent 기반 라우팅 ──
    routing_map: dict[str, RouteName] = {
        "buy": "memory_agent",
        "reorder": "memory_agent",
        "compare_platforms": "platform_agent",
        "refine": "platform_agent",
        "ask": "product_agent",
        "next": "product_agent",
        "confirm": "respond",
        "deny": "respond",
        "option_select": "respond",
        "quantity_change": "respond",
        "address_change": "respond",
    }
    return _decide(routing_map.get(intent, "respond"))


def after_platform_agent(state: ShoppingState) -> Literal["product_agent", "respond"]:
    """
    platform_agent 이후 분기.
    - platform_suggest: product_agent 건너뛰고 바로 respond (플랫폼 제안만)
    - 그 외: product_agent로 (랭킹/추천)
    """
    pending_type = (state.get("pending_action") or {}).get("type")
    if pending_type == "platform_suggest":
        return "respond"
    return "product_agent"


def after_reorder(state: ShoppingState) -> Literal["respond", "platform_agent"]:
    """reorder_node 이후 분기: URL 실패 시 platform_agent fallback."""
    if state.get("error") in ("reorder_url_failed", "reorder_no_match"):
        return "platform_agent"
    return "respond"


def after_memory_agent(state: ShoppingState) -> Literal["reorder_node", "platform_agent", "respond"]:
    """
    memory_agent 이후 분기.
    - reorder  → reorder_node (과거 구매 상품 직접 재주문)
    - buy      → platform_agent (선호도 로드 후 상품 검색)
    - 그 외    → respond (결제 완료 등)
    """
    intent = state.get("intent")
    stage = state.get("stage", "idle")
    pending_type = _ptype(state.get("pending_action"))

    def _decide(dest):
        agent_logger.log_router("memory_agent", dest, intent or "-", stage, pending_type)
        return dest

    if intent == "reorder":
        return _decide("reorder_node")
    if intent in ("buy", "refine", "compare_platforms"):
        return _decide("platform_agent")
    return _decide("respond")


def after_payment_agent(state: ShoppingState) -> Literal["memory_agent", "respond"]:
    """
    payment_agent 이후 분기.
    - stage=completed: memory_agent (구매이력 저장)
    - 그 외 (cart_shopping, payment_processing 등): respond로 바로
    """
    stage = state.get("stage", "idle")
    pending_type = _ptype(state.get("pending_action"))
    intent = state.get("intent") or "-"

    def _decide(dest):
        agent_logger.log_router("payment_agent", dest, intent, stage, pending_type)
        return dest

    if stage == "completed":
        return _decide("memory_agent")
    return _decide("respond")


def after_respond(state: ShoppingState) -> Literal["wait_for_input", "end"]:
    """respond 이후 계속 진행 여부 판단."""
    stage = state.get("stage", "idle")
    error = state.get("error")

    if stage in ("completed", "failed"):
        return "end"

    if error and "fatal" in error.lower():
        return "end"

    return "wait_for_input"
