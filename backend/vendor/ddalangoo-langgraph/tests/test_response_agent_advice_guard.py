"""WON-23 Unit 3 — product_decision_advice 답변에 카탈로그(가격) 데이터가
새어들지 않는지 확인하는 결정론적 가드(_reflect_no_catalog_claims)를
LLM 없이 고정한다."""
from src.agents.response_agent import _reflect_no_catalog_claims


def test_plain_advice_passes():
    ok, reason = _reflect_no_catalog_claims("요즘은 사과가 제철이라 더 맛있어요.")
    assert ok is True
    assert reason == ""


def test_price_like_value_fails():
    ok, reason = _reflect_no_catalog_claims("이건 12,900원이에요.")
    assert ok is False
    assert "12,900원" in reason


def test_price_without_comma_fails():
    ok, _ = _reflect_no_catalog_claims("이건 3000원이에요.")
    assert ok is False


def test_unrelated_word_containing_won_syllable_passes():
    # "원" 음절이 포함돼도 숫자+원 패턴이 아니면 오탐하면 안 된다
    # ("학원", "원래" 등은 가격이 아니다).
    ok, reason = _reflect_no_catalog_claims("원래 두 개 다 맛있어서 학원 근처에서도 인기예요.")
    assert ok is True
    assert reason == ""


def test_count_not_price_passes():
    # "3개"처럼 개수 표현은 가격이 아니므로 통과해야 한다.
    ok, _ = _reflect_no_catalog_claims("사과는 3개, 딸기는 5개씩 담아 먹기 좋아요.")
    assert ok is True
