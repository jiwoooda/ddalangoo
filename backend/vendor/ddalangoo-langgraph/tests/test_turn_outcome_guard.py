"""WON-50 Unit 3 semantic no-progress checks and response guard wiring."""
from __future__ import annotations

from typing import get_type_hints

from src.agents.nodes import reset_turn_observability_node, respond_node
from src.graph.builder import build_graph
from src.recovery.detectors import after_turn_outcome_guard, planned_response, turn_outcome_guard_node
from src.state.node_inputs import TurnOutcomeGuardInput, TurnOutcomeGuardUpdate
from src.state.schema import get_default_shopping_state


def _state(**updates):
    state = get_default_shopping_state("unit3", "session")
    state.update({"stage": "cart_shopping", "pending_action": {"type": "cart_review", "message": "확인할까요?"}})
    state.update(updates)
    return state


def test_turn_start_resets_recovery_and_captures_only_digests():
    state = _state(active_failure={"code": "old"}, recovery_status="safe_stopped")
    update = reset_turn_observability_node(state)

    assert update["active_failure"] is None
    assert update["recovery_status"] == "idle"
    assert update["turn_start_signature"]["planned_response_digest"]
    assert "확인할까요?" not in repr(update["turn_start_signature"])


def test_first_identical_outcome_records_no_progress_and_routes_to_recovery():
    state = _state()
    state["turn_start_signature"] = reset_turn_observability_node(state)["turn_start_signature"]

    update = turn_outcome_guard_node(state)

    assert update["active_failure"]["kind"] == "NO_PROGRESS"
    assert update["active_failure"]["code"] == "workflow.turn.no_progress"
    assert update["active_failure"]["context_keys"] == ["stage", "pending_action", "planned_response"]
    assert after_turn_outcome_guard(state | update) == "fallback_orchestrator"


def test_later_identical_outcome_marks_loop_without_replacing_first_failure():
    first_turn = _state()
    first_turn.update(reset_turn_observability_node(first_turn))
    first = turn_outcome_guard_node(first_turn)
    second_turn = first_turn | first
    second_turn.update(reset_turn_observability_node(second_turn))

    later = turn_outcome_guard_node(second_turn)

    assert later["active_failure"]["kind"] == "LOOP_DETECTED"
    assert later["active_failure"]["code"] == "workflow.turn.no_progress"
    assert later["repeated_signature_turns"] == 2


def test_ignored_response_candidate_change_still_detects_the_same_response():
    state = _state(immediate_response="OLD")
    state.update(reset_turn_observability_node(state))
    changed = state | {"immediate_response": "NEW"}

    update = turn_outcome_guard_node(changed)

    assert planned_response(changed) == "확인할까요?"
    assert update["active_failure"]["kind"] == "NO_PROGRESS"
    assert after_turn_outcome_guard(changed | update) == "fallback_orchestrator"


def test_planned_response_precedence_matches_pending_and_new_question_paths():
    pending = _state(immediate_response="IGNORED")
    question = _state(pending_action=None, immediate_response="새 질문")

    assert planned_response(pending) == respond_node(pending)["messages"][0]["content"] == "확인할까요?"
    assert planned_response(question) == respond_node(question)["messages"][0]["content"] == "새 질문"


def test_guard_uses_the_narrow_input_and_update_contracts():
    hints = get_type_hints(turn_outcome_guard_node)
    assert hints["state"] is TurnOutcomeGuardInput
    assert hints["return"] is TurnOutcomeGuardUpdate


def test_new_question_and_payment_boundary_continue_to_respond():
    state = _state()
    state["turn_start_signature"] = reset_turn_observability_node(state)["turn_start_signature"]
    changed = state | {"pending_action": {"type": "address_input", "message": "주소를 알려주세요."}}
    assert after_turn_outcome_guard(changed | turn_outcome_guard_node(changed)) == "respond"

    payment = state | {"stage": "payment_processing"}
    update = turn_outcome_guard_node(payment)
    assert "active_failure" not in update
    assert after_turn_outcome_guard(payment | update) == "respond"


def test_fallback_clarification_reaches_respond_without_guard_reentry():
    before = _state()
    before.update(reset_turn_observability_node(before))
    clarified = before | {
        "pending_action": {"type": "clarification", "message": "새로 확인할 정보가 있어요."},
        "needs_clarification": False,
    }

    guard_update = turn_outcome_guard_node(clarified)

    assert after_turn_outcome_guard(clarified | guard_update) == "respond"


def test_every_respond_entrance_flows_through_the_guard():
    graph = build_graph().get_graph()
    incoming = [edge.source for edge in graph.edges if edge.target == "respond"]

    assert incoming == ["turn_outcome_guard"]
    assert "turn_outcome_guard" in graph.nodes
