"""Unit 2 regression coverage for the two approved router no-edge cases."""
from __future__ import annotations

import pytest

import src.agents.fallback_orchestrator as fallback_module
from src.agents.fallback_orchestrator import FallbackDecision, fallback_orchestrator_node
from src.graph.builder import build_graph
from src.graph.router import after_fallback_orchestrator, after_product_agent, route
from src.recovery.nodes import transition_failure_node
from src.state.schema import get_default_shopping_state


def _state(**updates):
    state = get_default_shopping_state("unit2", "session")
    state.update({"confidence": 0.9, "needs_clarification": False})
    state.update(updates)
    return state


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            _state(
                stage="recipe_planning",
                intent="quantity_change",
                pending_action={"type": "ingredient_confirm"},
            ),
            {
                "kind": "UNHANDLED_TRANSITION",
                "source": "router",
                "code": "recipe.ingredient_confirm.no_edge",
                "stage": "recipe_planning",
                "pending_type": "ingredient_confirm",
                "intent": "quantity_change",
                "retryability": "safe_once",
                "side_effect_risk": "write",
                "context_keys": ["pending_action", "intent"],
            },
        ),
        (
            _state(
                stage="cart_shopping",
                intent="address_change",
                address_text="value is intentionally not recorded",
                pending_action={"type": "address_required"},
            ),
            {
                "kind": "UNHANDLED_TRANSITION",
                "source": "router",
                "code": "cart.address_required.no_edge",
                "stage": "cart_shopping",
                "pending_type": "address_required",
                "intent": "address_change",
                "retryability": "safe_once",
                "side_effect_risk": "write",
                "context_keys": ["pending_action", "intent", "address_text"],
            },
        ),
    ],
)
def test_approved_no_edges_route_and_record_deterministic_failure(state, expected):
    assert route(state) == "transition_failure"

    update = transition_failure_node(state)

    assert update["active_failure"] == expected
    assert "value is intentionally not recorded" not in repr(update["active_failure"])


def test_transition_failure_keeps_the_first_root_cause():
    first = {"kind": "UNHANDLED_TRANSITION", "code": "already.recorded"}
    state = _state(
        stage="recipe_planning",
        intent="quantity_change",
        pending_action={"type": "ingredient_confirm"},
        active_failure=first,
    )

    assert transition_failure_node(state)["active_failure"] is first


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(stage="cart_shopping", intent="ask", pending_action={"type": "cart_review"}), "respond"),
        (_state(stage="product_confirming", intent="confirm", quantity=None), "respond"),
        (_state(stage="searching", intent="ask"), "response_agent"),
        (_state(stage="payment_processing", intent="address_change", address_text="address"), "payment_agent"),
        (_state(intent="confirm", pending_action={"type": "cancel_confirm"}), "cancel"),
        (_state(stage="recipe_planning", intent="buy", pending_action={"type": "ingredient_confirm"}), "respond"),
    ],
)
def test_non_approved_fallbacks_keep_existing_destinations(state, expected):
    assert route(state) == expected


def test_search_error_remains_an_intentional_respond_path():
    assert after_product_agent(_state(error="no_candidates")) == "respond"


def test_transition_failure_is_wired_to_the_existing_recovery_entrypoint():
    graph = build_graph().get_graph()

    assert "transition_failure" in graph.nodes
    assert any(edge.source == "transition_failure" and edge.target == "fallback_orchestrator" for edge in graph.edges)


class _FakeLLM:
    def __init__(self, decision):
        self._decision = decision

    def invoke(self, _messages):
        return self._decision


def _failure_state(**updates):
    state = _state(**updates)
    state["active_failure"] = transition_failure_node(state)["active_failure"]
    return state


@pytest.mark.parametrize(
    "updates",
    [
        {
            "stage": "recipe_planning",
            "intent": "quantity_change",
            "pending_action": {"type": "ingredient_confirm"},
        },
        {
            "stage": "cart_shopping",
            "intent": "address_change",
            "address_text": "value is intentionally not recorded",
            "pending_action": {"type": "address_required"},
        },
    ],
)
@pytest.mark.parametrize("corrected_intent", [None, "address_change"])
def test_active_failure_recover_without_safe_intent_ends_at_respond(
    monkeypatch, updates, corrected_intent
):
    decision = FallbackDecision(
        action="recover",
        corrected_intent=corrected_intent,
        clarify_message="안전하게 다시 확인할게요.",
    )
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: _FakeLLM(decision))
    state = _failure_state(**updates)

    update = fallback_orchestrator_node(state)
    routed_state = state | update

    assert update["pending_action"]["type"] == "clarification"
    assert after_fallback_orchestrator(routed_state) == "respond"
    assert route(routed_state) == "respond"


def test_active_failure_recover_with_safe_intent_keeps_existing_recovery(monkeypatch):
    decision = FallbackDecision(action="recover", corrected_intent="refine")
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: _FakeLLM(decision))
    state = _failure_state(
        stage="recipe_planning",
        intent="quantity_change",
        pending_action={"type": "ingredient_confirm"},
    )

    update = fallback_orchestrator_node(state)

    assert update["intent"] == "refine"
    assert after_fallback_orchestrator(state | update) == "recipe_agent"


def test_fallback_contract_includes_active_failure():
    from src.state.node_inputs import FallbackOrchestratorInput

    assert "active_failure" in FallbackOrchestratorInput.__annotations__
