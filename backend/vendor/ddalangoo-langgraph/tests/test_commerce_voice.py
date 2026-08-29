"""Task 3 — commerce_voice 문구 생성기 테스트 (3층 전략).

  1층: 폴백 템플릿 = 순수 유닛. LLM을 강제로 끄고, fact 번들 → 결정론적 문구.
  2층: reflection 연동 = _FakeLLM 로 나쁜/좋은 출력을 주입해 폴백 전환 확인.
  3층: 실 LLM smoke (@pytest.mark.llm_smoke, 기본 실행 제외) — 죽지 않고
       reflection 통과하는 문자열을 반환하는지만.

WON-29 겹침으로 이번 스코프에서 제외된 지점(P14 no_address / P15 address_selected
결제흐름 / P22 fallback 가드)은 payment/node.py 배선 대상이 아니다 — 다만
commerce_voice 의 폴백 자체는 그 awaiting 값도 커버한다(호출부만 안 붙일 뿐).
"""
import json

import pytest

from src.utils import commerce_facts as cf
from src.utils import commerce_voice as cv


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch):
    """1층 기본값: LLM 경로를 끈다(_try_llm 이 None → 폴백). 2·3층은 개별로 되돌린다."""
    monkeypatch.setattr(cv, "_try_llm", lambda bundle, timeout: None)


# ── 1층: 폴백 템플릿 ──────────────────────────────────────────────────────

def test_fallback_continue_or_pay_single():
    bundle = cf.build_bundle(
        "continue_or_pay",
        cf.item_just_added(["참기름"], "오뚜기 참기름 500ml", 1),
        cf.single_item(["참기름"], "오뚜기 참기름 500ml", 1, 15900),
    )
    msg = cv.render_voice(bundle)
    assert "참기름" in msg and "1개" in msg
    assert "결제" in msg


def test_fallback_continue_or_pay_multi():
    cart = [
        {"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 1, "total": 12900},
        {"keywords": ["우유"], "product_name": "서울우유 1L", "quantity": 2, "total": 5600},
    ]
    bundle = cf.build_bundle(
        "continue_or_pay",
        cf.item_just_added(["우유"], "서울우유 1L", 2),
        cf.cart_contents(cart),
    )
    msg = cv.render_voice(bundle)
    assert "우유" in msg
    assert "결제" in msg


def test_fallback_cart_review_with_total():
    cart = [{"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 2, "total": 25800}]
    bundle = cf.build_bundle("cart_review", cf.cart_contents(cart))
    msg = cv.render_voice(bundle)
    assert "25,800원" in msg


def test_fallback_payment_method_choice():
    cart = [{"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 1, "total": 12900}]
    bundle = cf.build_bundle("payment_method_choice", cf.cart_contents(cart), cf.payment_method())
    msg = cv.render_voice(bundle)
    assert "12,900원" in msg
    assert "네이버" in msg


def test_fallback_payment_password():
    msg = cv.render_voice(cf.build_bundle("payment_password"))
    assert "비밀번호" in msg


def test_fallback_order_complete_with_delivery():
    bundle = cf.build_bundle(
        "order_complete",
        cf.order_placed("ORDER-ABC123"),
        cf.delivery_estimate("샛별배송", 0),
    )
    msg = cv.render_voice(bundle)
    assert "완료" in msg or "끝났" in msg
    assert "7시" in msg  # next_morning_7am 접미사


def test_fallback_order_complete_without_delivery():
    msg = cv.render_voice(cf.build_bundle("order_complete", cf.order_placed("ORDER-XYZ")))
    assert "완료" in msg or "끝났" in msg


def test_fallback_payment_retry():
    bundle = cf.build_bundle("payment_retry", cf.payment_error("execution_error"))
    msg = cv.render_voice(bundle)
    assert "다시" in msg


def test_fallback_what_to_buy():
    msg = cv.render_voice(cf.build_bundle("what_to_buy", cf.no_product_to_pay()))
    assert "무엇" in msg or "뭘" in msg


def test_fallback_selection_recheck():
    msg = cv.render_voice(cf.build_bundle("selection_recheck", cf.selection_rechecking()))
    assert "다시 확인" in msg or "확인하" in msg


def test_fallback_quantity():
    msg = cv.render_voice(cf.build_bundle("quantity"))
    assert "몇 개" in msg


def test_fallback_cancel_confirm():
    bundle = cf.build_bundle("cancel_confirm", cf.cancel_empties_cart())
    msg = cv.render_voice(bundle)
    assert "장바구니" in msg


def test_fallback_none_after_cancel():
    bundle = cf.build_bundle("none", cf.cart_cleared("cancel"))
    msg = cv.render_voice(bundle)
    assert isinstance(msg, str) and msg.strip()


def test_fallback_unanswerable_standalone_no_prefix():
    bundle = cf.build_bundle("payment_password", cf.unanswerable(None))
    msg = cv.render_voice(bundle)
    # 원래 pending 메시지를 접두어로 안 붙인다 (WON-26 §5-3)
    assert "비밀번호" in msg  # 대기 안내는 유지
    assert "어렵" in msg or "안내" in msg


def test_fallback_delivery_question_answer():
    bundle = cf.build_bundle("address_confirm", cf.delivery_estimate("로켓배송", 0))
    msg = cv.render_voice(bundle)
    assert "내일" in msg


def test_fallback_unknown_awaiting_is_safe_string():
    bundle = cf.build_bundle(cf.AWAITING_UNKNOWN)
    msg = cv.render_voice(bundle)
    assert isinstance(msg, str) and msg.strip()


def test_fallback_covers_every_awaiting_value():
    """폴백은 스키마의 모든 awaiting 값에 대해 비어있지 않은 문자열을 낸다."""
    for awaiting in cf.AWAITING_VALUES | {cf.AWAITING_UNKNOWN}:
        msg = cv.render_voice(cf.build_bundle(awaiting))
        assert isinstance(msg, str) and msg.strip(), awaiting


# ── 2층: reflection 연동 ─────────────────────────────────────────────────

class _FakeLLM:
    def __init__(self, text):
        self._text = text

    def invoke(self, *a, **kw):
        class _R:
            pass
        r = _R()
        r.content = self._text
        return r


def _use_fake_llm(monkeypatch, text):
    monkeypatch.undo()  # autouse _force_fallback 해제
    monkeypatch.setattr(cv, "_get_llm", lambda timeout=2.5: _FakeLLM(text))


def test_llm_good_output_is_returned_as_is(monkeypatch):
    _use_fake_llm(monkeypatch, "네, 딸기 두 개 담았어요. 결제할까요?")
    bundle = cf.build_bundle("continue_or_pay", cf.single_item(["딸기"], None, 2, 12900))
    assert cv.render_voice(bundle) == "네, 딸기 두 개 담았어요. 결제할까요?"


def test_llm_output_failing_reflection_falls_back(monkeypatch):
    # 금지어("가성비") 포함 → _reflect_elderly 실패 → 폴백 템플릿
    _use_fake_llm(monkeypatch, "이 상품은 가성비가 아주 좋은 플랫폼 최저가예요.")
    cart = [{"keywords": ["딸기"], "product_name": "x", "quantity": 1, "total": 12900}]
    msg = cv.render_voice(cf.build_bundle("payment_method_choice", cf.cart_contents(cart), cf.payment_method()))
    assert "가성비" not in msg
    assert "12,900원" in msg  # 폴백으로 떨어짐


def test_llm_empty_output_falls_back(monkeypatch):
    _use_fake_llm(monkeypatch, "   ")
    msg = cv.render_voice(cf.build_bundle("payment_password"))
    assert "비밀번호" in msg


def test_llm_exception_falls_back(monkeypatch):
    monkeypatch.undo()

    class _BoomLLM:
        def invoke(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(cv, "_get_llm", lambda timeout=2.5: _BoomLLM())
    msg = cv.render_voice(cf.build_bundle("payment_password"))
    assert "비밀번호" in msg


# ── 3층: 실 LLM smoke (기본 실행 제외) ───────────────────────────────────

@pytest.mark.llm_smoke
@pytest.mark.parametrize("bundle", [
    cf.build_bundle("payment_password"),
    cf.build_bundle(
        "payment_method_choice",
        cf.cart_contents([{"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 2, "total": 25800}]),
        cf.payment_method(),
    ),
    cf.build_bundle("order_complete", cf.order_placed("ORDER-1"), cf.delivery_estimate("로켓배송", 0)),
])
def test_llm_smoke_returns_valid_elderly_string(bundle, monkeypatch):
    monkeypatch.undo()  # autouse 폴백 픽스처(_force_fallback, conftest) 해제 → 실 LLM 경로
    msg = cv.render_voice(bundle)
    assert isinstance(msg, str) and msg.strip()
    ok, reason = cv._reflect_elderly(msg)
    assert ok, reason
