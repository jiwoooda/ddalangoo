from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import purchase_history_repository, user_preference_repository
from app.schemas.preference_report import PreferencePriceRange, PreferenceReportResponse


async def get_preference_report_db(db: AsyncSession, user_id: int) -> PreferenceReportResponse:
    """DB 캐시와 실제 구매이력으로 사용자 분석 리포트를 만든다."""
    cached_preference = await user_preference_repository.get_general_preference_db(db, user_id)
    histories = await purchase_history_repository.get_histories_by_user_id_db(
        db,
        user_id=user_id,
        limit=200,
    )

    interest_keywords = _top_labels_from_histories(histories, fields=("category", "keyword"), limit=4)
    preferred_brands = _preferred_brands(cached_preference, histories)
    repurchase_products = _repurchase_products(cached_preference, histories)
    preferred_platforms = _preferred_platforms(cached_preference, histories)
    price_range = _price_range(cached_preference, histories)
    summary = _string_or_none((cached_preference or {}).get("summary"))
    computed_at = _string_or_none((cached_preference or {}).get("computed_at"))

    has_data = bool(
        histories
        or interest_keywords
        or preferred_brands
        or repurchase_products
        or preferred_platforms
        or price_range
        or summary
    )

    return PreferenceReportResponse(
        userId=user_id,
        hasData=has_data,
        interestKeywords=interest_keywords,
        repurchaseProducts=repurchase_products,
        preferredPlatforms=preferred_platforms,
        preferredBrands=preferred_brands,
        priceRange=price_range,
        summary=summary,
        computedAt=computed_at,
    )


def _preferred_brands(cached_preference: dict[str, Any] | None, histories: list[dict]) -> list[str]:
    cached_brands = (cached_preference or {}).get("preferred_brands") or []
    labels: list[str] = []
    for item in cached_brands:
        if isinstance(item, dict):
            label = _string_or_none(item.get("brand"))
        else:
            label = _string_or_none(item)
        if label and label not in labels:
            labels.append(label)
    if labels:
        return labels[:5]

    return _top_labels_from_histories(histories, fields=("brand",), limit=5)


def _repurchase_products(cached_preference: dict[str, Any] | None, histories: list[dict]) -> list[str]:
    cached_products = (cached_preference or {}).get("repurchase_patterns") or []
    labels = [_string_or_none(item) for item in cached_products]
    labels = [label for label in labels if label]
    if labels:
        return _distinct(labels)[:5]

    product_counts = Counter(
        label
        for history in histories
        if (label := _string_or_none(history.get("product_name")))
    )
    return [name for name, count in product_counts.most_common() if count >= 2][:5]


def _preferred_platforms(cached_preference: dict[str, Any] | None, histories: list[dict]) -> list[str]:
    cached_platform = _string_or_none((cached_preference or {}).get("preferred_platform"))
    if cached_platform:
        return [_platform_label(cached_platform)]

    platform_counts = Counter(
        platform
        for history in histories
        if (platform := _string_or_none(history.get("platform")))
    )
    return [_platform_label(platform) for platform, _ in platform_counts.most_common(3)]


def _price_range(
    cached_preference: dict[str, Any] | None,
    histories: list[dict],
) -> PreferencePriceRange | None:
    cached_range = (cached_preference or {}).get("price_range") or {}
    average = _int_or_none(cached_range.get("avg") or cached_range.get("average"))
    min_price = _int_or_none(cached_range.get("min"))
    max_price = _int_or_none(cached_range.get("max"))
    if average or min_price or max_price:
        return PreferencePriceRange(average=average, min=min_price, max=max_price)

    prices = [
        price
        for history in histories
        if (price := _int_or_none(history.get("price_at_purchase"))) is not None and price > 0
    ]
    if not prices:
        return None
    return PreferencePriceRange(
        average=sum(prices) // len(prices),
        min=min(prices),
        max=max(prices),
    )


def _top_labels_from_histories(
    histories: list[dict],
    *,
    fields: tuple[str, ...],
    limit: int,
) -> list[str]:
    counts: Counter[str] = Counter()
    for history in histories:
        for field in fields:
            label = _string_or_none(history.get(field))
            if label:
                counts[label] += 1
    return [label for label, _ in counts.most_common(limit)]


def _distinct(labels: list[str]) -> list[str]:
    result: list[str] = []
    for label in labels:
        if label not in result:
            result.append(label)
    return result


def _platform_label(platform: str) -> str:
    normalized = platform.lower().strip()
    return {
        "kurly": "컬리",
        "coupang": "쿠팡",
        "naver": "네이버",
        "gmarket": "지마켓",
    }.get(normalized, platform)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
