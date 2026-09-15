"""Unit 4 recovery budget and safe-stop policy."""
from __future__ import annotations

import src.agents.fallback_orchestrator as fallback_module
from src.agents.fallback_orchestrator import FallbackDecision, _failure_fingerprint, fallback_orchestrator_node
from src.state.schema import get_default_shopping_state


class _FakeLLM:
    def __init__(self, decision: FallbackDecision | Exception):
        self.decision = decision
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


def _failure(**updates):
    failure = {
        "kind": "UNHANDLED_TRANSITION",
        "source": "router",
        "code": "recipe.ingredient_confirm.no_edge",
        "stage": "recipe_planning",
        "pending_type": "ingredient_confirm",
        "intent": "quantity_change",
        "retryability": "safe_once",
        "side_effect_risk": "write",
        "context_keys": ["pending_action", "intent"],
    }
    failure.update(updates)
    return failure


def _state(**updates):
    state = get_default_shopping_state("unit4", "session")
    state.update(
        {
            "stage": "recipe_planning",
            "intent": "quantity_change",
            "pending_action": {"type": "ingredient_confirm", "message": "continue?"},
            "confidence": 0.9,
            "needs_clarification": False,
            "active_failure": _failure(),
        }
    )
    state.update(updates)
    return state


def test_first_failure_uses_one_automatic_attempt(monkeypatch):
    llm = _FakeLLM(FallbackDecision(action="recover", corrected_intent="refine"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: llm)

    update = fallback_orchestrator_node(_state())

    assert llm.calls == 1
    assert update["recovery_attempts"] == 1
    assert update["recovery_status"] == "recovering"


def test_identical_failure_safe_stops_without_mutating_shopping_state(monkeypatch):
    llm = _FakeLLM(FallbackDecision(action="recover", corrected_intent="refine"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: llm)
    state = _state(
        recovery_fingerprint=_failure_fingerprint(_failure()),
        recovery_attempts=1,
        cart_items=[{"id": "cart"}],
        queue_items=[{"id": "queue"}],
        current_queue_index=2,
        selected_product={"id": "product"},
        order_id="order",
        payment={"id": "payment"},
    )

    update = fallback_orchestrator_node(state)

    assert llm.calls == 0
    assert update["recovery_status"] == "safe_stopped"
    assert update["recovery_attempts"] == 1
    message = update["pending_action"]["message"]
    assert "재료 수량 변경을 지금 처리하지 못했어요" in message
    assert "장바구니는 그대로 두었어요" in message
    assert "선택한 상품은 그대로 두었어요" in message
    assert "내용을 바꿔 다시 요청해 주세요" in message
    assert set(update).isdisjoint({"cart_items", "queue_items", "current_queue_index", "selected_product", "order_id", "payment"})


def test_different_failure_gets_a_fresh_attempt(monkeypatch):
    llm = _FakeLLM(FallbackDecision(action="recover", corrected_intent="refine"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: llm)
    old = _failure(code="old.failure")

    update = fallback_orchestrator_node(
        _state(recovery_fingerprint=_failure_fingerprint(old), recovery_attempts=1)
    )

    assert llm.calls == 1
    assert update["recovery_attempts"] == 1
    assert update["recovery_fingerprint"] == _failure_fingerprint(_failure())


def test_no_progress_and_loop_share_the_same_budget_fingerprint():
    no_progress = _failure(kind="NO_PROGRESS", code="workflow.turn.no_progress")
    loop = _failure(kind="LOOP_DETECTED", code="workflow.turn.no_progress")

    assert _failure_fingerprint(no_progress) == _failure_fingerprint(loop)


def test_payment_and_risk_gates_skip_the_llm(monkeypatch):
    llm = _FakeLLM(FallbackDecision(action="recover", corrected_intent="refine"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: llm)

    for state in (
        _state(stage="payment_processing"),
        _state(active_failure=_failure(kind="RISK_BLOCKED")),
        _state(active_failure=_failure(retryability="human_confirm")),
        _state(active_failure=_failure(side_effect_risk="high")),
    ):
        assert fallback_orchestrator_node(state)["recovery_status"] == "safe_stopped"
    assert llm.calls == 0


def test_write_risk_allows_safe_refine_but_denies_unsafe_correction(monkeypatch):
    safe = _FakeLLM(FallbackDecision(action="recover", corrected_intent="refine"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: safe)
    assert fallback_orchestrator_node(_state())["intent"] == "refine"

    unsafe = _FakeLLM(FallbackDecision(action="recover", corrected_intent="address_change"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: unsafe)
    update = fallback_orchestrator_node(_state())
    assert update["pending_action"]["type"] == "clarification"
    assert update["recovery_status"] == "waiting_user"
    assert update["recovery_fingerprint"] == _failure_fingerprint(_failure())
    assert update["recovery_attempts"] == 1
    assert fallback_orchestrator_node(_state() | update)["recovery_status"] == "safe_stopped"
    assert unsafe.calls == 1


def test_clarify_and_provider_error_wait_for_user(monkeypatch):
    clarify = _FakeLLM(FallbackDecision(action="clarify", clarify_message="Need detail"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: clarify)
    clarified = fallback_orchestrator_node(_state())
    assert clarified["recovery_status"] == "waiting_user"
    assert clarified["recovery_fingerprint"] == _failure_fingerprint(_failure())
    assert clarified["recovery_attempts"] == 1
    assert fallback_orchestrator_node(_state() | clarified)["recovery_status"] == "safe_stopped"
    assert clarify.calls == 1

    broken = _FakeLLM(RuntimeError("provider unavailable"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: broken)
    update = fallback_orchestrator_node(_state())
    assert update["recovery_status"] == "waiting_user"
    assert update["recovery_attempts"] == 1


def test_chat_persists_its_attempt_before_waiting_for_user(monkeypatch):
    chat = _FakeLLM(FallbackDecision(action="chat", chat_reply="Can I help?"))
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: chat)
    monkeypatch.setattr(fallback_module, "pick_and_start_engagement", lambda _user_id: None)

    chatted = fallback_orchestrator_node(_state())

    assert chatted["recovery_status"] == "waiting_user"
    assert chatted["recovery_fingerprint"] == _failure_fingerprint(_failure())
    assert chatted["recovery_attempts"] == 1
    assert fallback_orchestrator_node(_state() | chatted)["recovery_status"] == "safe_stopped"
    assert chat.calls == 1


def test_goal_shift_clears_goal_local_recovery_state(monkeypatch):
    llm = _FakeLLM(
        FallbackDecision(action="recover", corrected_intent="refine", reset_product_context=False)
    )
    monkeypatch.setattr(fallback_module, "_get_llm", lambda: llm)

    update = fallback_orchestrator_node(
        _state(goal_shift=True, recovery_fingerprint="previous", recovery_attempts=1)
    )

    assert update["recovery_fingerprint"] is None
    assert update["recovery_attempts"] == 0
