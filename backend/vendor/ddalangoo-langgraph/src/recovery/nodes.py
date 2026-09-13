"""Deterministic producers for recovery events."""
from __future__ import annotations

from src.recovery.types import FailureEvent, keep_first_failure
from src.state.schema import ShoppingState
from src.utils.agent_logger import _ptype


def _transition_failure_event(state: ShoppingState) -> FailureEvent:
    stage = state.get("stage", "idle")
    pending_type = _ptype(state.get("pending_action"))
    intent = state.get("intent")

    if (
        stage == "recipe_planning"
        and pending_type == "ingredient_confirm"
        and intent == "quantity_change"
    ):
        return {
            "kind": "UNHANDLED_TRANSITION",
            "source": "router",
            "code": "recipe.ingredient_confirm.no_edge",
            "stage": stage,
            "pending_type": pending_type,
            "intent": intent,
            "retryability": "safe_once",
            "side_effect_risk": "write",
            "context_keys": ["pending_action", "intent"],
        }

    if (
        stage == "cart_shopping"
        and pending_type == "address_required"
        and intent == "address_change"
        and state.get("address_text")
    ):
        return {
            "kind": "UNHANDLED_TRANSITION",
            "source": "router",
            "code": "cart.address_required.no_edge",
            "stage": stage,
            "pending_type": pending_type,
            "intent": intent,
            "retryability": "safe_once",
            "side_effect_risk": "write",
            "context_keys": ["pending_action", "intent", "address_text"],
        }

    raise ValueError("transition_failure_node received an unsupported route")


def transition_failure_node(state: ShoppingState) -> dict[str, FailureEvent]:
    """Record the first detected router no-edge without retaining user contents."""
    candidate = _transition_failure_event(state)
    return {"active_failure": keep_first_failure(state.get("active_failure"), candidate)}
