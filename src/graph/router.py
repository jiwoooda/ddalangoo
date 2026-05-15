from typing import Literal
from src.state.schema import ShoppingState

RouteName = Literal[
    "memory_agent",
    "platform_agent",
    "product_agent",
    "payment_agent",
    "respond",
    "interrupt_payment",
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

    # ── 1. 명확성 검사 ──
    if needs_clarification or confidence < 0.5 or intent == "unclear":
        return "respond"

    # ── 2. cancel은 어디서든 우선 처리 ──
    if intent == "cancel":
        if stage == "payment_processing":
            return "interrupt_payment"
        return "end"

    # ── 3. 결제 진행 중이면 Payment Subgraph가 처리 ──
    # option_select, address_change, quantity_change, confirm/deny 등은
    # payment_agent 내부 pending_action 기준으로 처리
    if stage == "payment_processing":
        return "payment_agent"

    # ── 4. 상품 확인 단계 ──
    if stage == "product_confirming":
        if intent == "confirm":
            return "payment_agent"

        if intent in ("deny", "next", "ask"):
            return "product_agent"

        if intent in ("refine", "compare_platforms"):
            return "platform_agent"

        if intent in ("quantity_change", "address_change", "option_select"):
            return "respond"

        return "respond"

    # ── 5. 검색 중 ──
    if stage == "searching":
        if intent == "cancel":
            return "end"

        if intent in ("refine", "compare_platforms"):
            return "platform_agent"

        if intent == "ask":
            return "respond"

        return "respond"

    # ── 6. idle / 기본 Intent 기반 라우팅 ──
    routing_map: dict[str, RouteName] = {
        "buy": "platform_agent",
        "reorder": "memory_agent",
        "compare_platforms": "platform_agent",
        "refine": "platform_agent",
        "ask": "product_agent",
        "next": "product_agent",

        # pending_action 없는 confirm/deny는 Intent Agent에서 unclear 처리되는 게 원칙
        "confirm": "respond",
        "deny": "respond",

        # 결제 전용 intent는 idle에서는 직접 처리하지 않음 -> 해당 요청 필요 없으므로 안내메세지만
        "option_select": "respond",
        "quantity_change": "respond",
        "address_change": "respond",
    }

    return routing_map.get(intent, "respond")


def after_reorder(state: ShoppingState) -> Literal["respond", "platform_agent"]:
    """reorder_node 이후 분기: URL 실패 시 platform_agent fallback."""
    if state.get("error") == "reorder_url_failed":
        return "platform_agent"
    return "respond"


def after_respond(state: ShoppingState) -> Literal["wait_for_input", "end"]:
    """respond 이후 계속 진행 여부 판단."""
    stage = state.get("stage", "idle")
    error = state.get("error")

    if stage in ("completed", "failed"):
        return "end"

    if error and "fatal" in error.lower():
        return "end"

    return "wait_for_input"
