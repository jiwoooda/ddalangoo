"""Unit 1 recovery contract: type shape, defaults, and lifecycle boundaries."""
from typing import get_args, get_type_hints

from src.recovery.types import (
    FREE_FORM_RECOVERY_EXCLUDED_STAGES,
    MAX_AUTOMATIC_RECOVERY_ATTEMPTS_PER_FINGERPRINT,
    FailureEvent,
    keep_first_failure,
)
from src.state import node_inputs, schema
from src.state.common_types import Intent, Stage
from src.state.schema import Intent as SchemaIntent
from src.state.schema import Stage as SchemaStage
from src.state.schema import get_default_shopping_state


def _event(code: str) -> FailureEvent:
    return {
        "kind": "UNHANDLED_TRANSITION",
        "source": "router",
        "code": code,
        "stage": "recipe_planning",
        "pending_type": "ingredient_confirm",
        "intent": "buy",
        "retryability": "safe_once",
        "side_effect_risk": "none",
        "context_keys": ["pending_action"],
    }


def test_failure_event_contains_only_shared_contract_fields():
    assert set(FailureEvent.__annotations__) == {
        "kind", "source", "code", "stage", "pending_type", "intent",
        "retryability", "side_effect_risk", "context_keys",
    }


def test_failure_event_runtime_hints_resolve_shared_literals():
    hints = get_type_hints(FailureEvent)

    assert hints["stage"] == Stage
    assert hints["intent"] == Intent | None
    assert SchemaStage is Stage
    assert SchemaIntent is Intent
    assert get_args(Stage) == (
        "idle", "searching", "product_confirming", "cart_shopping",
        "recipe_planning", "payment_processing", "payment_password_required",
        "completed", "failed",
    )
    assert get_args(Intent) == (
        "buy", "reorder", "confirm", "deny", "next", "refine",
        "compare_platforms", "quantity_change", "address_change", "option_select",
        "ask", "product_decision_advice", "cancel", "unclear",
    )


def test_default_state_initializes_recovery_contract():
    state = get_default_shopping_state("u1", "s1")
    assert state["active_failure"] is None
    assert state["turn_start_signature"] is None
    assert state["last_turn_signature"] is None
    assert state["repeated_signature_turns"] == 0
    assert state["recovery_fingerprint"] is None
    assert state["recovery_attempts"] == 0
    assert state["recovery_status"] == "idle"


def test_approved_recovery_policy_values_are_contractual():
    assert MAX_AUTOMATIC_RECOVERY_ATTEMPTS_PER_FINGERPRINT == 1
    assert FREE_FORM_RECOVERY_EXCLUDED_STAGES == {
        "payment_processing", "payment_password_required"
    }


def test_recovery_resets_have_explicit_turn_goal_and_session_scopes():
    default = get_default_shopping_state("u1", "s1")
    turn = schema.recovery_turn_reset()
    goal = schema.recovery_goal_reset()
    session = schema.recovery_session_reset()

    assert set(turn) == set(schema.RECOVERY_TURN_RESET_FIELDS)
    assert set(goal) == set(schema.RECOVERY_GOAL_RESET_FIELDS)
    assert set(session) == set(schema.RECOVERY_SESSION_RESET_FIELDS)
    assert set(turn).isdisjoint(goal)
    assert set(session) == set(turn) | set(goal)
    for reset in (turn, goal, session):
        for key, value in reset.items():
            assert value == default[key]


def test_first_failure_is_retained_for_the_turn():
    root = _event("recipe.ingredient_confirm.no_edge")
    symptom = _event("turn.no_progress")
    symptom["kind"] = "NO_PROGRESS"

    assert keep_first_failure(None, root) is root
    assert keep_first_failure(root, symptom) is root


def test_detector_guard_and_recovery_contracts_are_narrow():
    detector = set(node_inputs.FailureDetectorInput.__annotations__)
    guard = set(node_inputs.TurnOutcomeGuardInput.__annotations__)
    recovery = set(node_inputs.RecoveryOrchestratorInput.__annotations__)

    assert detector <= set(schema.ShoppingState.__annotations__)
    assert guard <= set(schema.ShoppingState.__annotations__)
    assert recovery <= set(schema.ShoppingState.__annotations__)
    assert "messages" not in detector | guard | recovery


def test_recovery_contract_imports_without_a_schema_cycle():
    import src.recovery.types  # noqa: F401
    import src.state.schema  # noqa: F401
