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
    update = fallback_orchestrator_node(_safe_stop_state(
        address_text="address-secret",
        payment={"number": "payment-secret", "password": "password-secret"},
        messages=[{"role": "user", "content": "private message"}],
    ))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert update["recovery_status"] == "safe_stopped"
    assert event["final_fallback_action"] == "safe_stop"
    assert event["response_generation_type"] == "template"
    assert event["trace_id"] != "session-secret"
    text = path.read_text(encoding="utf-8")
    for secret in (
        "private message", "private cart", "private product", "session-secret",
        "address-secret", "payment-secret", "password-secret",
    ):
        assert secret not in text


def test_active_failure_exits_log_once(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module,
        "_get_llm",
        lambda: _FakeLLM(FallbackDecision(action="clarify", clarify_message="specific question")),
    )

    fallback_orchestrator_node(_state(recovery_attempts=0, recovery_fingerprint=None))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["final_fallback_action"] == "clarify"
    assert event["response_generation_type"] == "generated"


def test_empty_clarify_message_logs_template_generation(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module, "_get_llm", lambda: _FakeLLM(FallbackDecision(action="clarify"))
    )

    update = fallback_orchestrator_node(_state(recovery_attempts=0, recovery_fingerprint=None))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert update["pending_action"]["message"] == fallback_module._DEFAULT_CLARIFY_FALLBACK
    assert event["response_generation_type"] == "template"


def test_empty_chat_reply_logs_template_generation(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module, "_get_llm", lambda: _FakeLLM(FallbackDecision(action="chat"))
    )
    monkeypatch.setattr(fallback_module, "pick_and_start_engagement", lambda _: None)

    update = fallback_orchestrator_node(_state(recovery_attempts=0, recovery_fingerprint=None))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert update["pending_action"]["message"] == fallback_module._DEFAULT_CLARIFY_FALLBACK
    assert event["response_generation_type"] == "template"


def test_unsafe_recover_downgrade_logs_template_for_empty_clarify_message(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module,
        "_get_llm",
        lambda: _FakeLLM(FallbackDecision(action="recover", corrected_intent="address_change")),
    )

    update = fallback_orchestrator_node(_state(recovery_attempts=0, recovery_fingerprint=None))

    event = json.loads(path.read_text(encoding="utf-8"))
    assert update["pending_action"]["message"] == fallback_module._DEFAULT_CLARIFY_FALLBACK
    assert event["response_generation_type"] == "template"


# active_failure가 있으면 corrected_intent 유무와 무관하게 위 test와 같은 분기(458행,
# "active_failure recover에 안전한 intent 보정이 없어 clarify로 강등")로 귀결된다.
# intent="unclear"를 줘도 472행 분기(교정 intent 없음 + intent unclear)에는 도달하지
# 않는다 — active_failure가 먼저 458행 조건에 걸려 그 분기가 선점한다. 472행 분기는
# active_failure가 없을 때만 도달 가능하며, 그 경우의 no-log semantics는 아래
# test_recover_downgrade_without_active_failure_skips_event_log가 검증한다.
def test_unsafe_recover_downgrade_without_corrected_intent_logs_template_for_empty_clarify_message(
    monkeypatch, tmp_path
):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module, "_get_llm", lambda: _FakeLLM(FallbackDecision(action="recover"))
    )

    update = fallback_orchestrator_node(
        _state(intent="unclear", recovery_attempts=0, recovery_fingerprint=None)
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert update["pending_action"]["message"] == fallback_module._DEFAULT_CLARIFY_FALLBACK
    assert event["response_generation_type"] == "template"


# 472행 분기(교정 intent 없음 + intent unclear)는 active_failure가 None일 때만
# 도달한다. _finalize_failure는 active_failure가 없으면 이벤트를 기록하지 않으므로
# (기존 semantics, 이 작업에서 변경하지 않음) 이 분기의 response_generation_type은
# 로그로 관측되지 않는다 — 그 사실 자체를 명시적으로 고정한다.
def test_recover_downgrade_without_active_failure_skips_event_log(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FALLBACK_EVENT_LOG_PATH", str(path))
    monkeypatch.setattr(
        fallback_module, "_get_llm", lambda: _FakeLLM(FallbackDecision(action="recover"))
    )

    update = fallback_orchestrator_node(
        _state(
            active_failure=None,
            intent="unclear",
            recovery_attempts=0,
            recovery_fingerprint=None,
        )
    )

    assert update["pending_action"]["message"] == fallback_module._DEFAULT_CLARIFY_FALLBACK
    assert not path.exists()


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


def test_safe_stop_without_verified_values_makes_no_preservation_claim():
    state = _state(cart_items=[], selected_product=None)
    message = render_safe_stop(build_safe_stop_plan(state["active_failure"], state))

    assert "장바구니는 그대로" not in message
    assert "선택한 상품은 그대로" not in message


def test_safe_stop_template_is_used_for_plan_or_renderer_error(monkeypatch):
    template = "지금 이 요청을 처리하지 못했어요. 다시 말씀해 주세요."
    monkeypatch.setattr(fallback_module, "build_safe_stop_plan", lambda *_: (_ for _ in ()).throw(RuntimeError()))
    assert fallback_orchestrator_node(_safe_stop_state())["pending_action"]["message"] == template

    class BrokenPlan:
        @property
        def failed_action(self):
            raise RuntimeError()

    assert render_safe_stop(BrokenPlan()) == template


def test_kind_specific_safe_stop_strategies_do_not_collapse_to_general_copy():
    no_progress = _state(active_failure={**_state()["active_failure"], "kind": "NO_PROGRESS", "code": "no_progress"})
    loop = _state(active_failure={**_state()["active_failure"], "kind": "LOOP_DETECTED", "code": "loop"})
    missing = _state(active_failure={**_state()["active_failure"], "kind": "MISSING_CONTEXT", "code": "missing"})
    risk = _state(active_failure={**_state()["active_failure"], "kind": "RISK_BLOCKED", "code": "risk"})
    execution = _state(active_failure={**_state()["active_failure"], "kind": "EXECUTION_FAILED", "code": "execution"})

    for state in (no_progress, loop):
        message = render_safe_stop(build_safe_stop_plan(state["active_failure"], state))
        assert "같은 요청을 계속 처리하는 일" in message
        assert "원하는 결과를 다르게 말씀해 주세요" in message
    assert "필요한 정보를 알려 주세요" in render_safe_stop(build_safe_stop_plan(missing["active_failure"], missing))
    assert "직접 확인하거나 필요한 확인을 진행해 주세요" in render_safe_stop(build_safe_stop_plan(risk["active_failure"], risk))
    assert "처리하지 못했어요" in render_safe_stop(build_safe_stop_plan(execution["active_failure"], execution))
