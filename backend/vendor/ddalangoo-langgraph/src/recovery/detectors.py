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
from src.state.node_inputs import TurnOutcomeGuardInput, TurnOutcomeGuardUpdate


def _digest(value: Any) -> str:
    """Return a stable digest so recovery state never retains user content."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def planned_response(state: TurnOutcomeGuardInput) -> str:
    """Mirror respond_node's message precedence without sending or persisting it."""
    stage = state.get("stage", "idle")
    intent = state.get("intent")
    immediate = state.get("immediate_response")
    explanation = state.get("explanation")
    pending = state.get("pending_action") or {}

    if pending.get("type") == "cancel_declined":
        return pending["message"]
    if pending.get("type") == "substitution_confirm" and intent == "deny":
        return immediate or "알겠습니다! 다른 상품을 찾아드릴까요?"
    if pending.get("type") == "address_confirm" and stage != "payment_processing":
        if intent == "confirm":
            return immediate or "알겠습니다!"
        if intent in ("deny", "address_change"):
            address = state.get("address_text") if intent == "address_change" else None
            if address:
                parts = address.split()
                short = " ".join(parts[:3]) + "..." if len(parts) > 3 else address
                return f"{short}로 등록했어요."
            return immediate or "알겠습니다! 새 배송지를 말씀해 주시겠어요?"
    if pending.get("type") == "product_select" and pending.get("message"):
        return pending["message"]
    if state.get("needs_clarification"):
        if state.get("last_agent") == "intent_agent":
            return immediate or state.get("clarification_reason") or "죄송해요, 잘 못 들었어요. 다시 한 번 말씀해 주시겠어요?"
        return pending.get("message") or immediate or state.get("clarification_reason") or "죄송해요, 잘 못 들었어요. 다시 한 번 말씀해 주시겠어요?"
    if stage == "product_confirming" and intent == "confirm" and not state.get("quantity"):
        return "몇 개 필요하세요?"
    if pending.get("message"):
        return pending["message"]
    if stage == "product_confirming":
        return explanation or "이 상품으로 주문할까요?"
    if stage == "payment_processing":
        return immediate or "결제를 계속 진행할까요?"
    if stage == "completed":
        return "주문이 완료되었어요!"
    if stage == "failed":
        return state.get("error") or "죄송해요, 처리하다가 문제가 생겼어요. 잠시 후 다시 시도해 주세요."
    return {
        "no_candidates": "죄송해요, 그 상품은 못 찾았어요. 다른 상품으로 다시 말씀해 주시겠어요?",
        "no_relevant_products": "죄송해요, 잘 맞는 상품을 못 찾았어요. 다른 말로 다시 한 번 말씀해 주시겠어요?",
        "invalid_keywords": "어떤 상품을 찾으시는지 조금 더 자세히 말씀해 주시면 제가 찾아드릴게요!",
        "no_more_products": "더 보여드릴 상품이 없네요. 다른 상품을 찾아볼까요?",
    }.get(state.get("error"), immediate or "무엇을 도와드릴까요?")


def turn_progress_signature(state: TurnOutcomeGuardInput) -> dict[str, Any]:
    """Describe business state and the planned response without raw text."""
    pending = state.get("pending_action") or {}
    return {
        "stage": state.get("stage", "idle"),
        "pending_type": pending.get("type"),
        "planned_response_digest": _digest(planned_response(state)),
        "queue_index": state.get("current_queue_index", 0),
        "queue_digest": _digest(state.get("queue_items") or []),
        "selected_product_digest": _digest(state.get("selected_product")),
        "cart_digest": _digest(state.get("cart_items") or []),
        "order_digest": _digest(state.get("order_id")),
        "payment_digest": _digest(state.get("payment")),
    }


def _repeat_kind(state: TurnOutcomeGuardInput, signature: dict[str, Any]) -> str | None:
    if state.get("stage") in FREE_FORM_RECOVERY_EXCLUDED_STAGES:
        return None
    if signature != state.get("turn_start_signature"):
        return None
    if signature == state.get("last_turn_signature") and (state.get("repeated_signature_turns") or 0) >= 1:
        return "LOOP_DETECTED"
    return "NO_PROGRESS"


def _no_progress_event(state: TurnOutcomeGuardInput, kind: Literal["NO_PROGRESS", "LOOP_DETECTED"]) -> FailureEvent:
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


def turn_outcome_guard_node(state: TurnOutcomeGuardInput) -> TurnOutcomeGuardUpdate:
    """Record no-progress once and retain semantic progress for the next turn."""
    signature = turn_progress_signature(state)
    kind = _repeat_kind(state, signature)
    repeats = (state.get("repeated_signature_turns") or 0) + 1 if kind else 0
    update: TurnOutcomeGuardUpdate = {
        "last_turn_signature": signature,
        "repeated_signature_turns": repeats,
    }
    if kind:
        update["active_failure"] = keep_first_failure(
            state.get("active_failure"), _no_progress_event(state, kind)
        )
    return update


def after_turn_outcome_guard(state: TurnOutcomeGuardInput) -> Literal["respond", "fallback_orchestrator"]:
    """Only a newly repeated semantic outcome takes the existing recovery path."""
    signature = turn_progress_signature(state)
    return "fallback_orchestrator" if _repeat_kind(state, signature) else "respond"
