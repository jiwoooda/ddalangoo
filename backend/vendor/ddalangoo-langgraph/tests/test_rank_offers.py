"""WON-22 Unit 6 — rank_offers(동일 identity 후보의 판매처 비교, 결정론적
정렬)를 고정. rank_products(_rank_with_metadata, LLM 기반)와 달리 순수
함수라 pytest로 직접 검증한다 — LLM 호출이 전혀 없어야 한다는 게 이 함수의
존재 이유이기도 하다(같은 제품이면 취향 판단이 필요 없음)."""
from src.agents.product_agent import rank_offers


def _offer(price, delivery_fee=0, delivery="일반배송", review_count=0):
    return {"price": price, "delivery_fee": delivery_fee, "delivery": delivery, "review_count": review_count}


def test_default_sorts_by_price_ascending():
    offers = [_offer(3200), _offer(2900), _offer(4000)]
    ranked = rank_offers(offers)
    assert [o["price"] for o in ranked] == [2900, 3200, 4000]


def test_condition_choepga_also_sorts_by_price():
    offers = [_offer(3200), _offer(2900)]
    ranked = rank_offers(offers, condition="최저가")
    assert ranked[0]["price"] == 2900


def test_condition_musongbe_prioritizes_free_shipping():
    offers = [_offer(2900, delivery_fee=3000), _offer(3200, delivery_fee=0)]
    ranked = rank_offers(offers, condition="무료배송")
    assert ranked[0]["delivery_fee"] == 0


def test_condition_ppareun_baesong_prioritizes_fast_delivery_labels():
    offers = [
        _offer(2900, delivery="일반배송"),
        _offer(3200, delivery="로켓배송"),
    ]
    ranked = rank_offers(offers, condition="빠른배송")
    assert ranked[0]["delivery"] == "로켓배송"


def test_condition_review_prioritizes_review_count():
    offers = [_offer(3200, review_count=1000), _offer(2900, review_count=10)]
    ranked = rank_offers(offers, condition="인기순")
    assert ranked[0]["review_count"] == 1000


def test_missing_price_sorted_last():
    offers = [_offer(2900), {"price": None, "delivery_fee": 0, "delivery": "", "review_count": 0}]
    ranked = rank_offers(offers)
    assert ranked[0]["price"] == 2900
    assert ranked[1]["price"] is None
