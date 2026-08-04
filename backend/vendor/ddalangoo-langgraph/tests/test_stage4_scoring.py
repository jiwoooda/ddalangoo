"""
Stage4 aggregator(순수 계산) 유닛 테스트. LLM 호출 없이 정규화/집계 로직만
검증한다 — 판단(LLM)과 계산(코드)의 경계를 지키는지가 핵심.
"""
from src.agents.product_agent import _assign_candidate_ids, PreferenceItemScore
from src.utils.aggregator import (
    aggregate,
    map_categorical_to_score,
    normalize_fixed_axes,
    normalize_weights,
)


def test_assign_candidate_ids_labels_in_order():
    candidates = [{"product_name": "a"}, {"product_name": "b"}, {"product_name": "c"}]
    tagged = _assign_candidate_ids(candidates)
    assert [c["_candidate_id"] for c in tagged] == ["A", "B", "C"]
    # 원본 필드는 보존
    assert tagged[0]["product_name"] == "a"


def test_normalize_fixed_axes_price_is_reversed():
    """가격은 낮을수록 유리 — 최저가가 price 축에서 1.0을 받아야 한다."""
    candidates = [
        {"_candidate_id": "A", "price": 10000, "rating": 4.5},
        {"_candidate_id": "B", "price": 20000, "rating": 4.5},
    ]
    result = normalize_fixed_axes(candidates)
    assert result["A"]["price"] == 1.0
    assert result["B"]["price"] == 0.0


def test_normalize_fixed_axes_review_is_forward():
    """리뷰점수는 높을수록 유리 — 최고평점이 review 축에서 1.0을 받아야 한다."""
    candidates = [
        {"_candidate_id": "A", "price": 10000, "rating": 4.0},
        {"_candidate_id": "B", "price": 10000, "rating": 4.8},
    ]
    result = normalize_fixed_axes(candidates)
    assert result["A"]["review"] == 0.0
    assert result["B"]["review"] == 1.0


def test_normalize_fixed_axes_missing_data_neutral():
    """가격/평점 정보가 없거나 후보 전체가 동일값이면 중립값(0.5)."""
    candidates = [{"_candidate_id": "A", "price": None, "rating": None}]
    result = normalize_fixed_axes(candidates)
    assert result["A"]["price"] == 0.5
    assert result["A"]["review"] == 0.5


def test_map_categorical_to_score():
    assert map_categorical_to_score("강한부합") == 1.0
    assert map_categorical_to_score("부합") == 0.66
    assert map_categorical_to_score("중립") == 0.33
    assert map_categorical_to_score("배치") == 0.0
    assert map_categorical_to_score("알수없음") == 0.33  # 안전한 기본값


def test_normalize_weights_sums_to_one():
    weights = normalize_weights({"price": 2.0, "review": 1.0, "preference": 1.0})
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights["price"] == 0.5


def test_normalize_weights_all_zero_falls_back_to_equal_split():
    weights = normalize_weights({"price": 0.0, "review": 0.0, "preference": 0.0})
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights["price"] == weights["review"] == weights["preference"]


def test_normalize_weights_negative_clamped_to_zero():
    weights = normalize_weights({"price": -1.0, "review": 1.0, "preference": 0.0})
    assert weights["price"] == 0.0


def test_aggregate_final_score_and_sort_order():
    candidates = [
        {"_candidate_id": "A", "product_name": "비싸고 안맞음", "price": 20000, "rating": 4.0},
        {"_candidate_id": "B", "product_name": "싸고 잘맞음", "price": 10000, "rating": 4.0},
    ]
    fixed_normalized = normalize_fixed_axes(candidates)
    items_by_id = {
        "A": [PreferenceItemScore(candidate_id="A", preference_item="가성비", match_level="배치", reasoning="안맞음")],
        "B": [PreferenceItemScore(candidate_id="B", preference_item="가성비", match_level="강한부합", reasoning="잘맞음")],
    }
    weights = {"price": 0.5, "review": 0.0, "preference": 0.5}

    ranked = aggregate(candidates, fixed_normalized, items_by_id, weights)

    assert [c["product_name"] for c in ranked] == ["싸고 잘맞음", "비싸고 안맞음"]
    assert ranked[0]["final_score"] == 1.0  # price 1.0*0.5 + preference 1.0*0.5
    assert ranked[0]["preference_item_breakdown"][0]["match_level"] == "강한부합"
    assert ranked[1]["final_score"] == 0.0


def test_aggregate_averages_multiple_preference_items_per_candidate():
    """서로 다른 방향을 가리키는 항목들은 뭉개지지 않고 평균으로 반영된다."""
    candidates = [{"_candidate_id": "A", "product_name": "x", "price": 10000, "rating": 4.0}]
    fixed_normalized = normalize_fixed_axes(candidates)
    items_by_id = {
        "A": [
            PreferenceItemScore(candidate_id="A", preference_item="저가", match_level="강한부합", reasoning="쌈"),
            PreferenceItemScore(candidate_id="A", preference_item="프리미엄", match_level="배치", reasoning="저가라 프리미엄 아님"),
        ],
    }
    ranked = aggregate(candidates, fixed_normalized, items_by_id, {"price": 0.0, "review": 0.0, "preference": 1.0})
    # (1.0 + 0.0) / 2 = 0.5
    assert ranked[0]["final_score"] == 0.5
    assert len(ranked[0]["preference_item_breakdown"]) == 2


def test_aggregate_missing_preference_items_defaults_neutral():
    """LLM이 특정 후보를 빠뜨려도(모델 오류) 중립 취급하고 죽지 않는다."""
    candidates = [{"_candidate_id": "A", "product_name": "x", "price": 10000, "rating": 4.0}]
    fixed_normalized = normalize_fixed_axes(candidates)
    ranked = aggregate(candidates, fixed_normalized, {}, {"price": 0.34, "review": 0.33, "preference": 0.33})
    assert ranked[0]["final_score"] is not None
    assert "preference_item_breakdown" not in ranked[0]  # pref 정보 자체가 없으면 필드 안 붙임
