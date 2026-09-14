"""Deterministic semantic progress checks before a user response."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Literal

from src.recovery.types import (
    FREE_FORM_RECOVERY_EXCLUDED_STAGES,
    FailureEvent,
    keep_first_failure,
)
from src.state.schema import ShoppingState


def _digest(value: Any) -> str:
    """Return a stable digest so recovery state never retains user content."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def turn_progress_signature(state: ShoppingState) -> dict[str, Any]:
    """Describe business state and the planned response without raw text."""
    pending = state.get("pending_action") or {}
    return {
        "stage": state.get("stage", "idle"),
        "pending_type": pending.get("type"),
        "pending_response_digest": _digest(pending.get("message")),
        "immediate_response_digest": _digest(state.get("immediate_response")),
        "explanation_digest": _digest(state.get("explanation")),
        "error_digest": _digest(state.get("error")),
        "queue_index": state.get("current_queue_index", 0),
        "queue_digest": _digest(state.get("queue_items") or []),
        "selected_product_digest": _digest(state.get("selected_product")),
        "cart_digest": _digest(state.get("cart_items") or []),
        "order_digest": _digest(state.get("order_id")),
        "payment_digest": _digest(state.get("payment")),
    }


def _repeat_kind(state: ShoppingState, signature: dict[str, Any]) -> str | None:
    if state.get("stage") in FREE_FORM_RECOVERY_EXCLUDED_STAGES:
        return None
    if signature != state.get("turn_start_signature"):
        return None
    if signature == state.get("last_turn_signature") and (state.get("repeated_signature_turns") or 0) >= 1:
        return "LOOP_DETECTED"
    return "NO_PROGRESS"


def _no_progress_event(state: ShoppingState, kind: Literal["NO_PROGRESS", "LOOP_DETECTED"]) -> FailureEvent:
    pending = state.get("pending_action") or {}
    return {
        "kind": kind,
        "source": "turn_outcome_guard",
        "code": "workflow.turn.no_progress",
        "stage": state.get("stage", "idle"),
        "pending_type": pending.get("type"),
        "intent": state.get("intent"),
        "retryability": "bounded",
        "side_effect_risk": "none",
        "context_keys": ["stage", "pending_action", "planned_response"],
    }


def turn_outcome_guard_node(state: ShoppingState) -> dict[str, Any]:
    """Record no-progress once and retain semantic progress for the next turn."""
    signature = turn_progress_signature(state)
    kind = _repeat_kind(state, signature)
    repeats = (state.get("repeated_signature_turns") or 0) + 1 if kind else 0
    update: dict[str, Any] = {
        "last_turn_signature": signature,
        "repeated_signature_turns": repeats,
    }
    if kind:
        update["active_failure"] = keep_first_failure(
            state.get("active_failure"), _no_progress_event(state, kind)
        )
    return update


def after_turn_outcome_guard(state: ShoppingState) -> Literal["respond", "fallback_orchestrator"]:
    """Only a newly repeated semantic outcome takes the existing recovery path."""
    signature = turn_progress_signature(state)
    return "fallback_orchestrator" if _repeat_kind(state, signature) else "respond"
