"""WON-20 Unit 3 — fallback_orchestrator 배선.

두 가지 수정:
1) 배선 버그: reset_product_context 판단이 action(recover/clarify/chat) 종류와
   무관하게 적용된다(예전엔 _recover_result() 안에서만 읽혀 chat/clarify면 버려짐).
2) 판단 소스: state["goal_shift"](Unit 2 intent_agent 산출)가 True면 재확인 없이
   신뢰해 리셋. False/None이면 기존처럼 LLM decision.reset_product_context 사용.

리셋은 WON-37 product_context_reset()+purchase_flow_reset() 재사용(새 로직 없음),
cart_items 는 유지(WON-37 결정).
"""
import pytest

import src.agents.fallback_orchestrator as fo
from src.agents.fallback_orchestrator import (
    FallbackDecision,
    _should_reset_product_context,
    fallback_orchestrator_node,
)
from src.state.schema import get_default_shopping_state
from src.state.node_inputs import FallbackOrchestratorInput


class _FakeLLM:
    def __init__(self, decision: FallbackDecision):
        self._d = decision

    def invoke(self, messages):
        return self._d


@pytest.fixture(autouse=True)
def _no_engagement(monkeypatch):
    # chat 브랜치가 db 를 건드리지 않게 — engagement 없음 → _clarify_result(chat_reply)
    monkeypatch.setattr(fo, "pick_and_start_engagement", lambda uid: None)


def _patch_llm(monkeypatch, **dec) -> FallbackDecision:
    d = FallbackDecision(**dec)
    monkeypatch.setattr(fo, "_get_llm", lambda: _FakeLLM(d))
    return d


def _state(goal_shift=None, text="TV 꺼줘", **over) -> dict:
    st = get_default_shopping_state("won20u3", "s")
    st["messages"] = [{"role": "user", "content": text}]
    st["fallback_stuck_turns"] = 1
    if goal_shift is not None:
        st["goal_shift"] = goal_shift
    st.update(over)
    return st


# ── 1. _should_reset_product_context: 판단 소스 우선순위 ────────────────

@pytest.mark.parametrize("goal_shift,llm_reset,expected", [
    (True,  False, True),   # Unit 2 확신 → action/LLM 무관하게 리셋
    (True,  True,  True),
    (False, True,  True),   # 애매영역 → LLM 판단을 그대로 (이제 honor)
    (False, False, False),
    (None,  True,  True),   # goal_shift 미설정 → 기존 LLM 판단
    (None,  False, False),
])
def test_should_reset_priority(goal_shift, llm_reset, expected):
    st = {} if goal_shift is None else {"goal_shift": goal_shift}
    d = FallbackDecision(action="chat", reset_product_context=llm_reset)
    assert _should_reset_product_context(st, d) is expected


# ── 2. 배선 버그 수정: action=chat 이어도 goal_shift=True 면 리셋 ───────

def test_chat_with_goal_shift_resets_context(monkeypatch):
    _patch_llm(monkeypatch, action="chat", chat_reply="네, 편하게 말씀하세요.",
               reset_product_context=False)
    st = _state(goal_shift=True, keywords=["우유"],
                selected_product={"product_name": "서울우유 1L"},
                recommended_products=[{"product_name": "서울우유 1L"}],
                recommendation_context={"purchase_count": 3},
                queue_items=[{"name": "우유"}])
    out = fallback_orchestrator_node(st)
    # WON-37 product_context_reset()
    assert out["keywords"] == []
    assert out["selected_product"] is None
    assert out["recommended_products"] == []
    # WON-37 purchase_flow_reset()
    assert out["queue_items"] == []
    assert out["recommendation_context"] is None
    assert out["pending_action"] is not None  # chat 의 결정값이 우선
    assert out["pending_action"]["type"] == "clarification"


def test_clarify_with_goal_shift_resets_context(monkeypatch):
    _patch_llm(monkeypatch, action="clarify", clarify_message="어떤 상품을 찾으세요?",
               reset_product_context=False)
    st = _state(goal_shift=True, keywords=["우유"],
                selected_product={"product_name": "X"})
    out = fallback_orchestrator_node(st)
    assert out["keywords"] == []
    assert out["selected_product"] is None
    assert out["pending_action"]["message"] == "어떤 상품을 찾으세요?"
    assert out["needs_clarification"] is False


# ── 3. 과확장 방지: goal_shift=False + LLM reset=False → 리셋 안 함 ─────

def test_chat_no_goal_shift_no_llm_reset_keeps_context(monkeypatch):
    _patch_llm(monkeypatch, action="chat", chat_reply="네.", reset_product_context=False)
    st = _state(goal_shift=False, keywords=["우유"],
                selected_product={"product_name": "X"})
    out = fallback_orchestrator_node(st)
    assert "keywords" not in out
    assert "selected_product" not in out
    assert "recommendation_context" not in out


# ── 4. 배선 버그 수정: goal_shift=False 여도 LLM reset=True 는 이제 honor ─

def test_chat_llm_reset_true_now_honored(monkeypatch):
    _patch_llm(monkeypatch, action="chat", chat_reply="네.", reset_product_context=True)
    st = _state(goal_shift=False, keywords=["우유"],
                selected_product={"product_name": "X"})
    out = fallback_orchestrator_node(st)
    assert out["keywords"] == []          # 예전엔 action=chat 이라 버려졌음
    assert out["selected_product"] is None


# ── 5. recover: goal_shift=True 면 LLM reset=False 여도 리셋 ───────────

def test_recover_with_goal_shift_resets_even_if_llm_said_false(monkeypatch):
    _patch_llm(monkeypatch, action="recover", corrected_intent="buy",
               corrected_keywords=["계란"], reset_product_context=False)
    st = _state(goal_shift=True, keywords=["우유"],
                selected_product={"product_name": "X"})
    out = fallback_orchestrator_node(st)
    assert out["intent"] == "buy"
    assert out["keywords"] == ["계란"]     # corrected 값이 reset 기본값 위에 얹힘
    assert out["selected_product"] is None  # goal_shift 로 리셋됨
    assert out["fallback_stuck_turns"] == 0


# ── 6. cart_items 는 goal_shift 리셋에도 유지 (WON-37 결정) ────────────

def test_cart_items_preserved_on_goal_shift_reset(monkeypatch):
    _patch_llm(monkeypatch, action="chat", chat_reply="네.", reset_product_context=False)
    st = _state(goal_shift=True, keywords=["우유"],
                cart_items=[{"product_name": "계란 한 판", "quantity": 1}])
    out = fallback_orchestrator_node(st)
    assert out["keywords"] == []
    assert "cart_items" not in out        # 리셋 대상 아님 — 그대로 유지


# ── 7. 계약 ──────────────────────────────────────────────────────────

def test_input_contract_has_goal_shift():
    assert "goal_shift" in FallbackOrchestratorInput.__annotations__


# ── 8. e2e (실 LLM) — action=chat 경로에서 WON-37 함수가 실제로 호출 ──

@pytest.mark.llm_smoke
def test_e2e_goal_shift_second_turn_resets_but_keeps_cart():
    import os
    os.environ.setdefault("DB_MODE", "mock")
    from datetime import datetime, timezone
    from src.graph.builder import build_graph
    from src.tools import db_client

    uid = "won20u3_e2e"
    db_client.save_profile(uid, {"onboarded_at": datetime.now(timezone.utc).isoformat()})
    g = build_graph()
    sid = f"won20u3-{uid}"
    cfg = {"configurable": {"thread_id": sid}}
    g.invoke(get_default_shopping_state(uid, sid), cfg)
    # 이미 쇼핑 문맥이 쌓였고 stuck_turns>=1 이라 다음 out_of_scope 발화가
    # fallback_orchestrator 로 넘어가는 상황을 직접 세팅.
    g.update_state(cfg, {
        "pending_action": None, "stage": "idle",
        "fallback_stuck_turns": 1,
        "keywords": ["우유"],
        "recommended_products": [{"product_name": "서울우유 1L"}],
        "selected_product": {"product_name": "서울우유 1L"},
        "cart_items": [{"product_name": "계란 한 판", "quantity": 1}],
    })
    g.update_state(cfg, {"messages": [{"role": "user", "content": "라디오 좀 틀어줘"}]})
    executed = []
    for u in g.stream(None, cfg, stream_mode="updates"):
        executed.extend(u.keys())
    final = g.get_state(cfg).values

    assert "fallback_orchestrator" in executed
    assert final["goal_shift"] is True
    assert final["keywords"] == []                    # WON-37 product_context_reset
    assert final["selected_product"] is None
    assert final["cart_items"] == [{"product_name": "계란 한 판", "quantity": 1}]  # 유지
