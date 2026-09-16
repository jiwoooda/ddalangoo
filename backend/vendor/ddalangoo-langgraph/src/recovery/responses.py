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
    kind = failure.get("kind")
    failed_action = {
        "recipe.ingredient_confirm.no_edge": "재료 수량 변경",
        "cart.address_required.no_edge": "배송지 변경",
    }.get(code)
    next_actions: tuple[str, ...]
    if failed_action is not None:
        next_actions = ("내용을 바꿔 다시 요청해 주세요", "직접 확인해 주세요")
    elif kind in {"NO_PROGRESS", "LOOP_DETECTED"}:
        failed_action = "같은 요청을 계속 처리하는 일"
        next_actions = ("원하는 결과를 다르게 말씀해 주세요", "직접 확인해 주세요")
    elif kind == "EXECUTION_FAILED":
        failed_action = "요청하신 작업"
        next_actions = ("잠시 후 다시 요청해 주세요", "직접 확인해 주세요")
    elif kind == "MISSING_CONTEXT":
        failed_action = "요청을 진행하는 일"
        next_actions = ("필요한 정보를 알려 주세요",)
    elif kind == "RISK_BLOCKED":
        failed_action = "요청하신 작업"
        next_actions = ("직접 확인하거나 필요한 확인을 진행해 주세요",)
    elif kind == "INTERPRETATION_FAILED":
        failed_action = "요청 내용"
        next_actions = ("원하는 내용을 다시 말씀해 주세요",)
    elif kind == "POSTCONDITION_FAILED":
        failed_action = "요청하신 작업 결과를 확인하는 일"
        next_actions = ("직접 확인해 주세요", "필요하면 다시 요청해 주세요")
    else:
        failed_action = "요청하신 작업"
        next_actions = ("내용을 바꿔 다시 요청해 주세요", "직접 확인해 주세요")
    preserved: list[str] = []
    if state.get("cart_items"):
        preserved.append("장바구니는 그대로 두었어요")
    if state.get("selected_product"):
        preserved.append("선택한 상품은 그대로 두었어요")
    return FallbackResponsePlan(
        response_type="safe_stop",
        failed_action=failed_action,
        preserved_facts=tuple(preserved),
        next_actions=next_actions,
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
