from math import log10
from typing import Literal


RankingMode = Literal["rule_based_v1", "llm_listwise_v1"]


def _keyword_score(candidate: dict, keywords: list[str]) -> float:
    """상품명/브랜드/카테고리에 검색 키워드가 얼마나 들어있는지 계산한다."""
    if not keywords:
        return 0.0

    haystack = " ".join(
        str(candidate.get(field) or "")
        for field in ("product_name", "name", "brand", "category")
    ).lower()
    matched_count = sum(1 for keyword in keywords if str(keyword).lower() in haystack)
    return min(1.0, matched_count / len(keywords))


def _price_score(candidate: dict, candidates: list[dict]) -> float:
    """같은 후보군 안에서 낮은 가격일수록 높은 점수를 준다."""
    prices = [
        price
        for price in (item.get("price") or item.get("current_price") for item in candidates)
        if isinstance(price, (int, float)) and price > 0
    ]
    price = candidate.get("price") or candidate.get("current_price")
    if not prices or not isinstance(price, (int, float)) or price <= 0:
        return 0.0

    min_price = min(prices)
    max_price = max(prices)
    if min_price == max_price:
        return 1.0
    return max(0.0, 1.0 - ((price - min_price) / (max_price - min_price)))


def _delivery_score(candidate: dict, condition: str | None) -> float:
    """배송 정보가 있고 빠른배송 조건에 가까우면 가산한다."""
    delivery_text = str(candidate.get("delivery_info") or candidate.get("delivery") or "").lower()
    if not delivery_text:
        return 0.0

    fast_keywords = ("새벽", "내일", "오늘", "로켓", "빠른", "당일")
    has_fast_delivery = any(keyword in delivery_text for keyword in fast_keywords)
    if condition == "빠른배송":
        return 1.0 if has_fast_delivery else 0.4
    return 0.8 if has_fast_delivery else 0.5


def _review_score(candidate: dict) -> float:
    """평점과 리뷰 수를 완만하게 반영한다."""
    rating = candidate.get("rating")
    review_count = candidate.get("review_count")
    rating_score = (float(rating) / 5.0) if isinstance(rating, (int, float)) else 0.0
    review_score = min(1.0, log10(float(review_count) + 1) / 4.0) if isinstance(review_count, (int, float)) else 0.0
    return (rating_score * 0.6) + (review_score * 0.4)


def _repurchase_match_score(candidate: dict, purchase_histories: list[dict] | None) -> float:
    """과거 구매 이력과 같은 상품/이름/카테고리인지 본다."""
    if not purchase_histories:
        return 0.0

    product_id = candidate.get("product_id")
    product_name = candidate.get("product_name") or candidate.get("name")
    category = candidate.get("category")

    for history in purchase_histories:
        if product_id and product_id == history.get("product_id"):
            return 1.0
        if product_name and product_name in {
            history.get("product_name_snapshot"),
            history.get("product_name"),
        }:
            return 0.9
        if category and category in {
            history.get("category_snapshot"),
            history.get("category"),
        }:
            return 0.4
    return 0.0


def rank_candidates_rule_based(
    candidates: list[dict],
    *,
    keywords: list[str],
    intent: str,
    condition: str | None = None,
    purchase_histories: list[dict] | None = None,
    preference_context: dict | None = None,
) -> list[dict]:
    """MVP용 백엔드 룰 기반 추천 랭킹."""
    weights = _weights_for_condition(
        intent=intent,
        condition=condition,
    )

    ranked = []
    for candidate in candidates:
        detail = {
            "keyword": _keyword_score(candidate, keywords),
            "price": _price_score(candidate, candidates),
            "delivery": _delivery_score(candidate, condition),
            "review": _review_score(candidate),
            "repurchase_match": _repurchase_match_score(candidate, purchase_histories),
            "weights": weights,
            "ranking_mode": "rule_based_v1",
        }
        score = sum(detail[name] * weight for name, weight in weights.items())
        ranked.append({
            **candidate,
            "score": round(score, 4),
            "score_detail": detail,
        })

    ranked.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
    return [
        {
            **candidate,
            "rank": index,
            "reason": candidate.get("reason") or "가격, 배송, 리뷰, 구매 이력을 기준으로 정렬했습니다.",
        }
        for index, candidate in enumerate(ranked, start=1)
    ]


def _weights_for_condition(intent: str, condition: str | None) -> dict[str, float]:
    """사용자 조건에 따라 룰 기반 점수 가중치를 조정한다."""
    weights = {
        "keyword": 0.25,
        "price": 0.20,
        "delivery": 0.20,
        "review": 0.20,
        "repurchase_match": 0.15,
    }
    if intent == "reorder":
        weights = {
            **weights,
            "keyword": 0.15,
            "repurchase_match": 0.35,
        }
    if condition in {"최저가", "가성비"}:
        return _normalize_weights({
            **weights,
            "price": 0.35,
            "delivery": 0.15,
            "review": 0.15,
        })
    if condition == "빠른배송":
        return _normalize_weights({
            **weights,
            "price": 0.15,
            "delivery": 0.35,
        })
    if condition in {"리뷰좋은", "인기순"}:
        return _normalize_weights({
            **weights,
            "price": 0.15,
            "review": 0.35,
        })
    if condition == "무료배송":
        return _normalize_weights({
            **weights,
            "price": 0.15,
            "delivery": 0.30,
            "review": 0.15,
        })
    return _normalize_weights(weights)


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """가중치 합이 항상 1이 되도록 정규화한다."""
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {
        name: round(value / total, 6)
        for name, value in weights.items()
    }


async def rank_candidates_with_llm(
    candidates: list[dict],
    *,
    keywords: list[str],
    intent: str,
    condition: str | None = None,
    purchase_histories: list[dict] | None = None,
    preference_context: dict | None = None,
) -> list[dict]:
    """LLM listwise ranking 자리. 실제 프롬프트/모델 결정 전까지는 명시적으로 막아둔다."""
    raise NotImplementedError("llm_listwise_v1 ranking은 아직 구현되지 않았습니다.")


async def rank_candidates(
    candidates: list[dict],
    *,
    keywords: list[str],
    intent: str,
    condition: str | None = None,
    purchase_histories: list[dict] | None = None,
    preference_context: dict | None = None,
    mode: RankingMode = "rule_based_v1",
) -> list[dict]:
    """추천 후보 랭킹 진입점. mode만 바꾸면 룰 기반/LLM 기반을 전환할 수 있다."""
    if mode == "rule_based_v1":
        return rank_candidates_rule_based(
            candidates,
            keywords=keywords,
            intent=intent,
            condition=condition,
            purchase_histories=purchase_histories,
            preference_context=preference_context,
        )

    if mode == "llm_listwise_v1":
        return await rank_candidates_with_llm(
            candidates,
            keywords=keywords,
            intent=intent,
            condition=condition,
            purchase_histories=purchase_histories,
            preference_context=preference_context,
        )

    raise ValueError(f"Unsupported ranking mode: {mode}")
