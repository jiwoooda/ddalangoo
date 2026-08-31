"""WON-38 Unit 1 — classify_payment_question 의 (topic, type) 판단 고정.

조사 표 11문구 + substring 충돌(#10) + 미매칭/None 케이스.
이 함수는 아직 어떤 노드에도 연결되지 않았다 — 순수 계산만 검증.
"""
import pytest

from src.utils.question_classifier import classify_payment_question as clf


# ── 조사 표 11문구 ─────────────────────────────────────────────────────

TABLE = [
    ("네이버페이 말고 다른 걸로 결제돼요?", "payment_method", "what"),
    ("카드는 어떻게 등록해요?",              "payment_method", "procedure"),
    ("카드로 결제하려면 어디서 해요?",        "payment_method", "procedure"),
    ("결제수단은 뭐가 있어요?",              "payment_method", "what"),
    ("돈은 어떻게 치러야 한대유?",           "payment_method", "procedure"),
    ("배송은 언제 와요?",                   "delivery",       "what"),
    ("배송비는 얼마예요?",                  "delivery",       "what"),
    ("택배는 어떻게 받아요?",               "delivery",       "procedure"),
    ("주소는 어디다 적어요?",               "address",        "procedure"),
    ("배송지를 어떻게 바꿔요?",             "address",        "procedure"),
    ("취소하면 배송은 어떻게 돼요?",         "cancel",         "what"),   # 취소 우선
]


@pytest.mark.parametrize("text,topic,qtype", TABLE)
def test_investigation_table(text, topic, qtype):
    assert clf(text) == {"topic": topic, "type": qtype}


# ── substring 충돌(#10) 명시적 검증 ───────────────────────────────────

def test_baesongji_is_address_not_delivery():
    """'배송지'가 '배송'에 걸려 delivery 로 오매칭되면 안 된다 (조사 #10)."""
    for t in ("배송지 바꿔주세요", "배송지가 어디로 돼 있어요?", "배송지 등록 어떻게 해요"):
        assert clf(t)["topic"] == "address", t


def test_delivery_still_matches_bare_baesong():
    """'배송지'가 아닌 순수 배송 질문은 여전히 delivery."""
    assert clf("배송 언제 와요?")["topic"] == "delivery"
    assert clf("택배 도착했어요?")["topic"] == "delivery"


# ── 우선순위: 취소 > 주소 > 배송 > 결제수단 ───────────────────────────

def test_topic_priority_cancel_wins():
    assert clf("취소하면 배송비는 어떻게 돼요?") == {"topic": "cancel", "type": "what"}
    assert clf("결제 취소돼요?") == {"topic": "cancel", "type": "what"}


def test_topic_priority_address_over_delivery():
    assert clf("배송지 주소를 어디서 바꿔요?")["topic"] == "address"


# ── None 케이스 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["이거 맛있어요?", "안녕하세요", "", "   ", "우유 한 개 더 담아줘"])
def test_unrelated_returns_none_none(text):
    assert clf(text) == {"topic": None, "type": None}


def test_type_is_none_only_when_topic_is_none():
    got = clf("배송 어떻게 와요?")
    assert got["topic"] is not None and got["type"] is not None


# ── type 판단 단독 ────────────────────────────────────────────────────

@pytest.mark.parametrize("text,qtype", [
    ("결제수단 뭐 있어요?", "what"),
    ("결제 어떻게 해요?", "procedure"),
    ("카드 어디에 넣어요?", "procedure"),
    ("결제 방법 알려주세요", "procedure"),
    ("배송비 얼마예요?", "what"),
    ("배송지 신청은 어떻게?", "procedure"),
])
def test_type_markers(text, qtype):
    assert clf(text)["type"] == qtype
