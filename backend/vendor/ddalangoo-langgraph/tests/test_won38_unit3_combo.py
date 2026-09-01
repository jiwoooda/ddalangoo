"""WON-38 Unit 3 — payment/node.py::_payment_flow_question_fact 를
state["question_classification"] (topic, type) 조합표로 전환 + (payment_method,
procedure) 신규 fact.

- 조합표 6갈래 정확한 fact
- question_classification 없음/None → classify_payment_question 폴백 (WON-35 회귀 방지)
- 자체 키워드 상수(_*_QUESTION_KEYWORDS) 제거 확인
- commerce_voice._answer_line 이 신규 fact 를 문구화
"""
import pytest

import src.payment.node as pn
from src.utils import commerce_facts as cf
from src.utils import commerce_voice as cv
from src.utils.question_classifier import classify_payment_question


def _state(text: str, qc=..., **extra) -> dict:
    st = {
        "messages": [{"role": "user", "content": text}],
        "selected_product": {"delivery": "로켓배송", "delivery_fee": 0},
    }
    if qc is not ...:                     # 명시적으로 넘기면(None 포함) 그대로
        st["question_classification"] = qc
    st.update(extra)
    return st


# ── 조합표 6갈래 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("qc,expected_fact_type", [
    ({"topic": "payment_method", "type": "what"},      "payment_method"),
    ({"topic": "payment_method", "type": "procedure"}, "payment_method_fixed_no_registration"),
    ({"topic": "delivery", "type": "what"},            "delivery_estimate"),
    ({"topic": "cancel", "type": "what"},              "cancel_available"),
])
def test_combo_table_returns_expected_fact(qc, expected_fact_type):
    fact = pn._payment_flow_question_fact(_state("무관한 원문", qc=qc))
    assert fact is not None and fact["fact_type"] == expected_fact_type


@pytest.mark.parametrize("qc", [
    {"topic": "delivery", "type": "procedure"},   # 조사 #8 — 배송 절차 전용 답 없음
    {"topic": "address", "type": "procedure"},    # address 는 Unit 4(response_agent) 몫
    {"topic": None, "type": None},
])
def test_combo_table_none_for_unhandled(qc):
    assert pn._payment_flow_question_fact(_state("무관한 원문", qc=qc)) is None


# ── 방어: question_classification 없음/None → 폴백 (WON-35 회귀 방지) ────

def test_missing_question_classification_falls_back_to_classifier():
    # 필드 자체가 없음(narrow-contract 드롭 / 그래프 밖 직접 호출)
    st = _state("카드는 어떻게 등록해요?")            # qc 안 넣음
    assert "question_classification" not in st
    fact = pn._payment_flow_question_fact(st)
    assert fact["fact_type"] == "payment_method_fixed_no_registration"


def test_none_question_classification_falls_back():
    fact = pn._payment_flow_question_fact(_state("배송 언제 와요?", qc=None))
    assert fact["fact_type"] == "delivery_estimate"


@pytest.mark.parametrize("text,expected", [
    ("카드 뭐로 되나요?",            "payment_method"),
    ("카드는 어떻게 등록해요?",       "payment_method_fixed_no_registration"),
    ("카드 번호 어디서 입력해요?",    "payment_method_fixed_no_registration"),
    ("돈은 어떻게 치러야 한대유?",    "payment_method_fixed_no_registration"),
    ("배송 언제 와요?",             "delivery_estimate"),
    ("이거 취소돼요?",              "cancel_available"),
    ("취소하면 배송은 어떻게 돼요?",  "cancel_available"),
    ("이 우유 유기농이에요?",        None),
])
def test_fallback_path_covers_investigation_table(text, expected):
    fact = pn._payment_flow_question_fact(_state(text))   # qc 없음 → 폴백
    got = fact["fact_type"] if fact else None
    assert got == expected, (text, got)


# ── 자체 키워드 상수 제거 ──────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "_PAYMENT_METHOD_QUESTION_KEYWORDS", "_DELIVERY_QUESTION_KEYWORDS", "_CANCEL_QUESTION_KEYWORDS",
])
def test_own_keyword_constants_removed(name):
    assert not hasattr(pn, name), f"{name} 는 Unit 3 에서 조합표로 대체돼야 한다"


# ── 신규 fact 모양 + Voice 문구화 ─────────────────────────────────────

def test_new_fact_shape():
    f = cf.payment_method_fixed_no_registration()
    assert f["fact_type"] == "payment_method_fixed_no_registration"
    assert f.get("method") == "네이버페이"
    assert f.get("registration_supported") is False


def test_answer_line_phrases_new_fact():
    line = cv._answer_line({"payment_method_fixed_no_registration": cf.payment_method_fixed_no_registration()})
    assert "네이버페이" in line
    assert ("등록" in line or "변경" in line) and ("어려" in line or "직접" in line)


# ── WON-35 cancel 분기 그대로 흡수 확인 ───────────────────────────────

def test_won35_cancel_branch_absorbed():
    for t in ("이거 취소돼요?", "지금 취소 가능해요?", "취소하면 배송은 어떻게 돼요?"):
        assert pn._payment_flow_question_fact(_state(t)) == {"fact_type": "cancel_available", "when": "before_confirm"}
