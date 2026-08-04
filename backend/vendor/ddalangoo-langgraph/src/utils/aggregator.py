"""
Stage4 Aggregation — LLM 콜 없는 순수 계산.

판단(LLM)과 계산(코드)의 경계: 정규화/카테고리→숫자 매핑/가중합은 이미
정답이 있는 산술이라 LLM 개입 없이 여기서 결정론적으로 계산한다. LLM에게
이 계산을 tool call로 시키면 불필요한 왕복만 늘고 이득이 없다.
"""
from typing import Any

_CATEGORICAL_SCORE = {
    "강한부합": 1.0,
    "부합": 0.66,
    "중립": 0.33,
    "배치": 0.0,
}

_FIXED_AXES = ("price", "review")
_ALL_AXES = ("price", "review", "preference")


def map_categorical_to_score(label: str) -> float:
    return _CATEGORICAL_SCORE.get(label, _CATEGORICAL_SCORE["중립"])


def normalize_fixed_axes(candidates: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """
    가격(낮을수록 유리 → 역방향)/리뷰점수(높을수록 유리 → 정방향)를
    후보군 내 min-max로 0~1 정규화한다. candidate는 "_candidate_id" 키로
    식별된다 (product_agent가 라벨을 붙여서 넘긴다).
    """
    prices = [c["price"] for c in candidates if isinstance(c.get("price"), (int, float))]
    ratings = [c["rating"] for c in candidates if isinstance(c.get("rating"), (int, float))]
    price_min, price_max = (min(prices), max(prices)) if prices else (0, 0)
    rating_min, rating_max = (min(ratings), max(ratings)) if ratings else (0, 0)

    result: dict[str, dict[str, float]] = {}
    for c in candidates:
        cid = c["_candidate_id"]
        price = c.get("price")
        if isinstance(price, (int, float)) and price_max > price_min:
            price_score = 1 - (price - price_min) / (price_max - price_min)
        else:
            price_score = 0.5  # 후보 전체가 동일가이거나 가격 정보 없음 — 중립값
        rating = c.get("rating")
        if isinstance(rating, (int, float)) and rating_max > rating_min:
            review_score = (rating - rating_min) / (rating_max - rating_min)
        else:
            review_score = 0.5
        result[cid] = {"price": price_score, "review": review_score}
    return result


def normalize_weights(raw_weights: dict[str, float]) -> dict[str, float]:
    """axis→weight dict를 합이 1이 되도록 정규화. 음수는 0으로 clamp."""
    clamped = {axis: max(raw_weights.get(axis, 0.0), 0.0) for axis in _ALL_AXES}
    total = sum(clamped.values())
    if total <= 0:
        return {axis: 1 / len(_ALL_AXES) for axis in _ALL_AXES}
    return {axis: w / total for axis, w in clamped.items()}


def _average_preference_score(items: list[Any]) -> float:
    """후보 하나에 달린 preference_item 판정들(soft_preferences 항목별)의 평균."""
    if not items:
        return _CATEGORICAL_SCORE["중립"]
    return sum(map_categorical_to_score(i.match_level) for i in items) / len(items)


def aggregate(
    candidates: list[dict[str, Any]],
    fixed_normalized: dict[str, dict[str, float]],
    items_by_id: dict[str, list[Any]],
    weights: dict[str, float],
) -> list[dict[str, Any]]:
    """
    후보별 final_score + axis_contributions를 계산해 final_score 내림차순으로
    정렬한 리스트를 반환한다. 원본 candidate dict를 복사해 확장하므로
    기존 필드(product_name, price, product_url...)는 그대로 보존된다.

    preference 축 점수는 항목(soft_preferences 하나하나)별 개별 판정의
    평균이다 — 뭉쳐서 하나로 판정하면 서로 다른 방향을 가리키는 신호의
    근거가 뭉개지므로, 항목 단위 판정 결과(items_by_id)를 평균 낸다.
    """
    scored: list[dict[str, Any]] = []
    for c in candidates:
        cid = c["_candidate_id"]
        norm = fixed_normalized.get(cid, {"price": 0.5, "review": 0.5})
        items = items_by_id.get(cid) or []
        preference_score = _average_preference_score(items)

        contributions = {
            "price": round(weights.get("price", 0.0) * norm["price"], 4),
            "review": round(weights.get("review", 0.0) * norm["review"], 4),
            "preference": round(weights.get("preference", 0.0) * preference_score, 4),
        }

        enriched = dict(c)
        enriched["final_score"] = round(sum(contributions.values()), 4)
        enriched["axis_contributions"] = contributions
        if items:
            enriched["preference_item_breakdown"] = [
                {
                    "preference_item": i.preference_item,
                    "match_level": i.match_level,
                    "reasoning": i.reasoning,
                }
                for i in items
            ]
        scored.append(enriched)

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored
