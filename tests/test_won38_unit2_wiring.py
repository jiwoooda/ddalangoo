"""WON-38 Unit 2 — intent_agent 배선: _PAYMENT_QUESTION_KEYWORDS 중복 제거 +
classify_payment_question 결과를 state["question_classification"] 에 실어 보냄.

- intent_agent_node 가 매 턴 question_classification 을 채우는지 (11 조사 표 문구, LLM mock)
- _PAYMENT_QUESTION_KEYWORDS 가 코드에서 완전히 사라졌는지
- _should_trust_ask_over_clarification 게이트가 여전히 같은 역할(결제/배송 질문이면 신뢰)
- 그래프 e2e 로 state 에 실제로 실리는지 (@llm_smoke)
"""
import pytest

import src.agents.intent_agent as ia
from src.agents.intent_agent import IntentOutput
from src.utils.question_classifier import classify_payment_question
from src.state.schema import get_default_shopping_state


TABLE = [
    ("네이버페이 말고 다른 걸로 결제돼요?", "payment_method", "what"),
    ("카드는 어떻게 등록해요?",              "payment_method", "procedure"),
    ("카드로 결제하려면 어디서 해요?",       "payment_method", "procedure"),
    ("결제수단은 뭐가 있어요?",             "payment_method", "what"),
    ("돈은 어떻게 치러야 한대유?",          "payment_method", "procedure"),
    ("배송은 언제 와요?",                  "delivery",       "what"),
    ("배송비는 얼마예요?",                 "delivery",       "what"),
    ("택배는 어떻게 받아요?",              "delivery",       "procedure"),
    ("주소는 어디다 적어요?",              "address",        "procedure"),
    ("배송지를 어떻게 바꿔요?",            "address",        "procedure"),
    ("취소하면 배송은 어떻게 돼요?",        "cancel",         "what"),
]


class _FakeLLM:
    """intent_agent 의 structured LLM 을 대체 — 최소 IntentOutput 반환."""
    def invoke(self, messages):
        return IntentOutput(intent="ask", keywords=[], confidence=0.9,
                            needs_clarification=False, immediate_response="네.")


@pytest.fixture
def _fake_intent_llm(monkeypatch):
    monkeypatch.setattr(ia, "_get_llm", lambda: _FakeLLM())


def _run_node(user_text: str) -> dict:
    st = get_default_shopping_state("user_test", "won38u2")
    st["messages"] = [{"role": "user", "content": user_text}]
    return ia.intent_agent_node(st)


# ── 1. 배선: question_classification 이 result 에 채워짐 ──────────────────

@pytest.mark.parametrize("text,topic,qtype", TABLE)
def test_intent_node_sets_question_classification(_fake_intent_llm, text, topic, qtype):
    result = _run_node(text)
    assert result["question_classification"] == {"topic": topic, "type": qtype}
    # 공용 함수와 동일한 값이어야 한다 (별도 로직 아님).
    assert result["question_classification"] == classify_payment_question(text)


def test_intent_node_question_classification_none_for_unrelated(_fake_intent_llm):
    result = _run_node("우유 한 개 사줘")
    assert result["question_classification"] == {"topic": None, "type": None}


def test_degraded_path_also_sets_question_classification(monkeypatch):
    """LLM 파싱 실패(축소 응답) 경로에서도 필드가 채워진다."""
    class _BoomLLM:
        def invoke(self, m):
            raise ValueError("structured output 파싱 실패")
    monkeypatch.setattr(ia, "_get_llm", lambda: _BoomLLM())
    st = get_default_shopping_state("user_test", "won38u2")
    st["messages"] = [{"role": "user", "content": "카드는 어떻게 등록해요?"}]
    result = ia.intent_agent_node(st)
    assert result.get("degraded_mode") is True
    assert result["question_classification"] == {"topic": "payment_method", "type": "procedure"}


# ── 2. 중복 키워드 목록 제거 ────────────────────────────────────────────

def test_payment_question_keywords_removed():
    assert not hasattr(ia, "_PAYMENT_QUESTION_KEYWORDS"), \
        "_PAYMENT_QUESTION_KEYWORDS 는 Unit 2 에서 제거돼야 한다 (payment/node.py 와의 의도적 복제 해소)"


# ── 3. _should_trust_ask_over_clarification 게이트 역할 유지 ─────────────

def test_gate_still_trusts_payment_questions():
    f = ia._should_trust_ask_over_clarification
    pt = next(iter(ia._PAYMENT_PENDING_TYPES))
    # clarification_reason 이 채워진(LLM 이 근거를 댄) 경우 — 결제/배송 키워드가
    # 있으면 여전히 신뢰(교정)한다.
    assert f("ask", True, "발화에서 언급한 품목이 없고...", 0.3, pt, "카드는 어떻게 등록해요?") is True
    assert f("ask", True, "무슨 배송 말인지 불명확", 0.3, pt, "배송은 언제 와요?") is True
    # 결제/배송과 무관한 진짜 모호한 ask 는 신뢰하지 않는다.
    assert f("ask", True, "그거가 뭔지 불명확", 0.3, pt, "그거 얼마예요?") is False


# ── 4. 그래프 e2e — state 에 실제로 실림 ────────────────────────────────

@pytest.mark.llm_smoke
@pytest.mark.parametrize("text,topic,qtype", [TABLE[1], TABLE[8], TABLE[10]])
def test_e2e_question_classification_reaches_state(text, topic, qtype):
    import uuid
    from dotenv import load_dotenv
    load_dotenv()
    from src.graph.builder import build_graph

    tid = f"won38u2-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": tid}}
    g = build_graph()
    init = get_default_shopping_state("user_001", tid)
    init["conversation_id"] = abs(hash(tid)) % 1_000_000
    init["messages"] = [{"role": "user", "content": text}]
    g.invoke(init, cfg)
    for _ in g.stream(None, cfg, stream_mode="updates"):
        pass
    st = g.get_state(cfg).values
    assert st.get("question_classification") == {"topic": topic, "type": qtype}, st.get("question_classification")
