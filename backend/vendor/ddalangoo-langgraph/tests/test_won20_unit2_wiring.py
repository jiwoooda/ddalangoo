"""WON-20 Unit 2 — intent_agent 배선: classify_scope 결과를 state["scope"]/
state["goal_shift"] 에 실어 보내고, high-confidence out_of_scope 발화를 1턴째
정중한 범위 안내로 마감한다(ask+needs_clarification 오분류 제거).

- intent_agent_node 가 매 턴 scope/goal_shift 를 채우는지 (LLM mock)
- scope=="out_of_scope" 일 때 intent=unclear + needs_clarification=False +
  immediate_response 가 정중한 범위 안내로 바뀌는지
- bridgeable / in_scope 발화는 기존 분류를 안 건드리는지 (Phase 1 보수적)
- degraded 경로에서도 필드가 채워지는지
- schema 기본값 / IntentAgentUpdate 계약에 필드가 있는지
- 그래프 e2e (@llm_smoke)
"""
import pytest

import src.agents.intent_agent as ia
from src.agents.intent_agent import IntentOutput, _OUT_OF_SCOPE_RESPONSE
from src.utils.scope_classifier import classify_scope
from src.state.schema import get_default_shopping_state
from src.state.node_inputs import IntentAgentUpdate


# ── LLM mock ──────────────────────────────────────────────────────────

class _FakeLLM:
    """intent_agent 의 structured LLM 대체 — '모호하다'고 보는 최악의 경우를
    흉내낸다(ask + needs_clarification=True). 이 상태에서도 out_of_scope 면
    코드가 정중한 안내로 덮어써야 한다."""
    def __init__(self, intent="ask", needs_clarification=True):
        self._intent = intent
        self._nc = needs_clarification

    def invoke(self, messages):
        return IntentOutput(
            intent=self._intent, keywords=[], confidence=0.3,
            needs_clarification=self._nc, clarification_reason="상품명이 없어요",
            immediate_response="어떤 상품을 찾으세요?",
        )


@pytest.fixture
def _fake_intent_llm(monkeypatch):
    monkeypatch.setattr(ia, "_get_llm", lambda: _FakeLLM())


def _run_node(user_text: str) -> dict:
    st = get_default_shopping_state("won20u2_user", "won20u2")
    st["messages"] = [{"role": "user", "content": user_text}]
    return ia.intent_agent_node(st)


# ── 1. 배선: scope / goal_shift 가 result 에 채워짐 ─────────────────────

_SCOPE_TABLE = [
    ("TV 꺼줘",               "out_of_scope", True),
    ("인터넷 좀 켜줘",        "out_of_scope", True),
    ("아들한테 전화 걸어줘",  "out_of_scope", True),
    ("대출 상담 좀 받고 싶은데", "out_of_scope", True),
    ("우유 사줘",             "in_scope",     False),
    ("다른 거 보여줘",        "in_scope",     False),
    ("아이고 힘드네",         "bridgeable",   False),
    ("손주가 보고 싶네",      "bridgeable",   False),
]


@pytest.mark.parametrize("text,scope,goal_shift", _SCOPE_TABLE)
def test_intent_node_sets_scope(_fake_intent_llm, text, scope, goal_shift):
    result = _run_node(text)
    assert result["scope"] == scope
    assert result["goal_shift"] is goal_shift
    # 공용 함수와 동일한 값이어야 한다 (별도 로직 아님).
    expected = classify_scope(text)
    assert result["scope"] == expected["scope"]
    assert result["goal_shift"] == expected["goal_shift"]


# ── 2. out_of_scope → 1턴째 정중한 범위 안내 ──────────────────────────

@pytest.mark.parametrize("text", ["TV 꺼줘", "인터넷 좀 켜줘", "라디오 틀어줘", "아들한테 전화 걸어줘"])
def test_out_of_scope_gets_polite_boundary(_fake_intent_llm, text):
    result = _run_node(text)
    assert result["intent"] == "unclear"
    assert result["needs_clarification"] is False
    assert result["clarification_reason"] is None
    msg = result["immediate_response"]
    assert msg and "어려" in msg          # 정직한 거절("도와드리기 어려운")
    assert "찾으세요" not in msg           # 엉뚱한 상품 되물음이 아님
    assert msg != "어떤 상품을 찾으세요?"


# ── 3. bridgeable / in_scope 는 기존 분류를 안 건드린다 ────────────────

@pytest.mark.parametrize("text", ["아이고 힘드네", "손주가 보고 싶네", "다른 거 보여줘", "이건 별로인데"])
def test_non_out_of_scope_untouched(_fake_intent_llm, text):
    """Phase 1 보수적: out_of_scope 가 아니면 out-of-scope 분기가 건드리지 않는다
    (intent 를 unclear 로 강제하지 않고, fake LLM 이 낸 ask + needs_clarification=
    True 를 그대로 둔다). buy 트리거가 있는 발화는 기존 force-correction 대상이라
    여기 포함하지 않는다."""
    result = _run_node(text)
    assert result["scope"] != "out_of_scope"
    assert result["intent"] == "ask"          # unclear 로 강제되지 않음
    assert result["needs_clarification"] is True
    assert result["immediate_response"] != _OUT_OF_SCOPE_RESPONSE


# ── 4. degraded 경로에서도 필드가 채워짐 ──────────────────────────────

def test_degraded_path_also_sets_scope(monkeypatch):
    class _BoomLLM:
        def invoke(self, m):
            raise ValueError("structured output 파싱 실패")
    monkeypatch.setattr(ia, "_get_llm", lambda: _BoomLLM())
    st = get_default_shopping_state("won20u2_user", "won20u2")
    st["messages"] = [{"role": "user", "content": "TV 꺼줘"}]
    result = ia.intent_agent_node(st)
    assert result.get("degraded_mode") is True
    assert result["scope"] == "out_of_scope"
    assert result["goal_shift"] is True


# ── 5. schema 기본값 / 계약 ──────────────────────────────────────────

def test_default_state_has_scope_fields():
    st = get_default_shopping_state("u", "s")
    assert st["scope"] is None
    assert st["goal_shift"] is False


def test_intent_update_contract_has_scope_fields():
    ann = IntentAgentUpdate.__annotations__
    assert "scope" in ann
    assert "goal_shift" in ann


# ── 6. 그래프 e2e (실 LLM) ──────────────────────────────────────────

@pytest.mark.llm_smoke
def test_e2e_tv_off_gets_boundary_first_turn():
    import os
    os.environ.setdefault("DB_MODE", "mock")
    from datetime import datetime, timezone
    from src.graph.builder import build_graph
    from src.tools import db_client

    uid = "won20u2_e2e"
    db_client.save_profile(uid, {"onboarded_at": datetime.now(timezone.utc).isoformat()})
    g = build_graph()
    sid = f"won20u2-{uid}"
    cfg = {"configurable": {"thread_id": sid}}
    g.invoke(get_default_shopping_state(uid, sid), cfg)
    g.update_state(cfg, {"pending_action": None, "stage": "idle"})

    g.update_state(cfg, {"messages": [{"role": "user", "content": "TV 꺼줘"}]})
    for _ in g.stream(None, cfg, stream_mode="updates"):
        pass
    final = g.get_state(cfg).values
    msgs = final.get("messages") or []
    reply = msgs[-1].get("content") if isinstance(msgs[-1], dict) else getattr(msgs[-1], "content", "")

    assert final["scope"] == "out_of_scope"
    assert "어려" in reply
    assert "찾으세요" not in reply and "구매하실까요" not in reply
