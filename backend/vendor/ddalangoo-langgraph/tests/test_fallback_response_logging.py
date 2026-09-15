import json

import src.agents.fallback_orchestrator as fallback_module
from src.agents.fallback_orchestrator import FallbackDecision, fallback_orchestrator_node
from src.recovery.responses import build_safe_stop_plan, render_safe_stop
from src.state.schema import get_default_shopping_state


class _FakeLLM:
    def __init__(self, decision):
        self.decision = decision

    def invoke(self, _messages):
        return self.decision


def _state(**updates):
    state = get_default_shopping_state("user", "session-secret")
    state.update({
        "stage": "recipe_planning",
        "intent": "quantity_change",
        "pending_action": {"type": "ingredient_confirm", "message": "private message"},
        "active_failure": {
            "kind": "UNHANDLED_TRANSITION", "source": "router",
            "code": "recipe.ingredient_confirm.no_edge", "stage": "recipe_planning",
            "pending_type": "ingredient_confirm", "intent": "quantity_change",
            "retryability": "safe_once", "side_effect_risk": "write", "context_keys": [],
        },
        "recovery_attempts": 1,
        "recovery_fingerprint": "fingerprint", "cart_items": [{"name": "private cart"}],
        "selected_product": {"name": "private product"},
    })
    state.update(updates)
    return state


def _safe_stop_state(**updates):
    state = _state(**updates)
    state["recovery_fingerprint"] = fallback_module._failure_fingerprint(state["active_failure"])
    return state


def test_safe_stop_response_uses_verified_context_without_internal_terms():
    message = render_safe_stop(build_safe_stop_plan(_state()["active_failure"], _state()))

    assert "재료 수량 변경" in message
    assert "장바구니는 그대로" in message
    assert "선택한 상품은 그대로" in message
    assert "fallback" not in message.lower()
    assert "자동 진행" not in message


def test_fallback_event_is_persistent_and_excludes_raw_values(monkeypatch, tmp_path):
    path = tmp_path / "fallback.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    update = fallback_orchestrator_node(_safe_stop_state())

    event = json.loads(path.read_text(encoding="utf-8"))
    assert update["recovery_status"] == "safe_stopped"
    assert event["final_fallback_action"] == "safe_stop"
    assert event["response_generation_type"] == "template"
    assert event["session_ref"] != "session-secret"
    text = path.read_text(encoding="utf-8")
    for secret in ("private message", "private cart", "private product", "session-secret"):
        assert secret not in text


def test_active_failure_exits_log_once(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module, "_get_llm", lambda: _FakeLLM(FallbackDecision(action="clarify"))
    )

    fallback_orchestrator_node(_state(recovery_attempts=0, recovery_fingerprint=None))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["final_fallback_action"] == "clarify"
    assert event["response_generation_type"] == "generated"


def test_recovered_failure_logs_once(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module, "_get_llm",
        lambda: _FakeLLM(FallbackDecision(action="recover", corrected_intent="refine")),
    )

    fallback_orchestrator_node(_state(recovery_attempts=0, recovery_fingerprint=None))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["final_fallback_action"] == "recovered"
    assert event["response_generation_type"] == "none"


def test_logger_write_error_never_changes_fallback_update(monkeypatch, tmp_path):
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(tmp_path))
    update = fallback_orchestrator_node(_safe_stop_state())

    assert update["recovery_status"] == "safe_stopped"
