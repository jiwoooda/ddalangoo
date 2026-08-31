"""WON-35 Unit 3 — payment/node.py::_payment_flow_question_fact 의 취소 분기.

결제 확정 전(pending) 대기 상태에서 "취소돼요?" 류 질문이 cancel_available
fact 로 답을 받고, 기존 delivery/payment_method 질문 동작에는 회귀가 없는지.
"""
from src.payment.node import _payment_flow_question_fact


def _state(text: str) -> dict:
    return {
        "messages": [{"role": "user", "content": text}],
        "selected_product": {"delivery": "로켓배송", "delivery_fee": 0},
    }


def test_cancel_question_returns_cancel_available_fact():
    fact = _payment_flow_question_fact(_state("이거 취소돼요?"))
    assert fact == {"fact_type": "cancel_available", "when": "before_confirm"}


def test_cancel_possible_question_returns_cancel_available_fact():
    fact = _payment_flow_question_fact(_state("지금 취소 가능해요?"))
    assert fact == {"fact_type": "cancel_available", "when": "before_confirm"}


def test_delivery_question_still_returns_delivery_estimate():
    fact = _payment_flow_question_fact(_state("배송 언제 와요?"))
    assert fact["fact_type"] == "delivery_estimate"


def test_payment_method_question_still_returns_payment_method():
    fact = _payment_flow_question_fact(_state("카드 뭐로 되나요?"))
    assert fact["fact_type"] == "payment_method"


def test_unrelated_question_still_none():
    assert _payment_flow_question_fact(_state("이 우유 유기농이에요?")) is None


def test_cancel_keyword_wins_over_delivery_when_both_present():
    # "취소하면 배송은?" 같은 겹침에서 확정 전 취소 안내가 우선한다.
    fact = _payment_flow_question_fact(_state("취소하면 배송은 어떻게 돼요?"))
    assert fact == {"fact_type": "cancel_available", "when": "before_confirm"}
