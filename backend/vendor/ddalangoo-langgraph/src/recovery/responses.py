"""Deterministic, user-facing wording for bounded fallback stops."""
from dataclasses import dataclass
from typing import Any


_DEFAULT_MESSAGE = "지금 이 요청을 처리하지 못했어요. 다시 말씀해 주세요."


@dataclass(frozen=True)
class FallbackResponsePlan:
    response_type: str
    failed_action: str
    preserved_facts: tuple[str, ...]
    next_actions: tuple[str, ...]


def build_safe_stop_plan(failure: dict[str, Any], state: dict[str, Any]) -> FallbackResponsePlan:
    code = failure.get("code")
    failed_action = {
        "recipe.ingredient_confirm.no_edge": "재료 수량 변경",
        "cart.address_required.no_edge": "배송지 변경",
    }.get(code, "요청하신 작업")
    preserved: list[str] = []
    if state.get("cart_items"):
        preserved.append("장바구니는 그대로 두었어요")
    if state.get("selected_product"):
        preserved.append("선택한 상품은 그대로 두었어요")
    return FallbackResponsePlan(
        response_type="safe_stop",
        failed_action=failed_action,
        preserved_facts=tuple(preserved),
        next_actions=("내용을 바꿔 다시 요청해 주세요", "직접 확인해 주세요"),
    )


def render_safe_stop(plan: FallbackResponsePlan) -> str:
    try:
        parts = [f"{plan.failed_action}을 지금 처리하지 못했어요."]
        if plan.preserved_facts:
            parts.append(". ".join(plan.preserved_facts) + ".")
        parts.append(" 또는 ".join(plan.next_actions) + ".")
        return " ".join(parts)
    except Exception:
        return _DEFAULT_MESSAGE
