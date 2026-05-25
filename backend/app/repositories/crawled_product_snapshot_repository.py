from datetime import UTC, date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import CrawledProductSnapshot


def _snapshot_to_dict(snapshot: CrawledProductSnapshot) -> dict:
    """ORM CrawledProductSnapshot을 서비스/테스트에서 쓰기 쉬운 dict로 변환한다."""
    return {
        "id": snapshot.id,
        "platform": snapshot.platform,
        "external_product_id": snapshot.external_product_id,
        "external_product_url": snapshot.external_product_url,
        "crawl_keyword": snapshot.crawl_keyword,
        "crawl_source": snapshot.crawl_source,
        "raw_product_name": snapshot.raw_product_name,
        "raw_brand": snapshot.raw_brand,
        "raw_category": snapshot.raw_category,
        "raw_price": snapshot.raw_price,
        "raw_original_price": snapshot.raw_original_price,
        "raw_discount_rate": snapshot.raw_discount_rate,
        "raw_delivery_info": snapshot.raw_delivery_info,
        "raw_rating": snapshot.raw_rating,
        "raw_review_count": snapshot.raw_review_count,
        "raw_image_url": snapshot.raw_image_url,
        "raw_is_sold_out": snapshot.raw_is_sold_out,
        "raw_payload": snapshot.raw_payload,
        "normalized_name": snapshot.normalized_name,
        "normalized_brand": snapshot.normalized_brand,
        "normalized_category": snapshot.normalized_category,
        "normalized_sub_category": snapshot.normalized_sub_category,
        "normalized_volume": snapshot.normalized_volume,
        "normalized_price": snapshot.normalized_price,
        "normalized_original_price": snapshot.normalized_original_price,
        "normalized_discount_rate": snapshot.normalized_discount_rate,
        "normalized_delivery_type": snapshot.normalized_delivery_type,
        "normalized_rating": snapshot.normalized_rating,
        "normalized_review_count": snapshot.normalized_review_count,
        "normalized_is_available": snapshot.normalized_is_available,
        "product_id": snapshot.product_id,
        "normalization_status": snapshot.normalization_status,
        "normalization_error": snapshot.normalization_error,
        "crawled_at": snapshot.crawled_at,
        "created_at": snapshot.created_at,
    }


def _string_or_none(value: Any) -> str | None:
    """raw 값은 원본 보존 목적이라 숫자/boolean도 문자열로 안전하게 저장한다."""
    if value is None:
        return None
    return str(value)


def _json_safe(value: Any) -> Any:
    """JSONB raw_payload에 들어갈 수 있도록 datetime 등 비 JSON 값을 안전하게 바꾼다."""
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


async def create_crawled_product_snapshot_db(
    db: AsyncSession,
    data: dict,
) -> dict:
    """
    외부 검색/크롤링 raw 상품 데이터를 snapshot으로 저장한다.

    여기서는 정제를 끝내지 않고 pending 상태로 남긴다.
    이후 정제 로직이 normalized_*와 product_id를 채운다.
    """
    raw_product_name = (
        data.get("raw_product_name")
        or data.get("product_name")
        or data.get("name")
    )
    if not raw_product_name:
        raise ValueError("raw_product_name 또는 product_name이 필요합니다.")

    snapshot = CrawledProductSnapshot(
        platform=data["platform"],
        external_product_id=data.get("external_product_id"),
        external_product_url=data.get("external_product_url") or data.get("product_url") or data.get("url"),
        crawl_keyword=data.get("crawl_keyword") or data.get("keyword"),
        crawl_source=data.get("crawl_source") or "search",
        raw_product_name=str(raw_product_name),
        raw_brand=_string_or_none(data.get("raw_brand") or data.get("brand")),
        raw_category=_string_or_none(data.get("raw_category") or data.get("category")),
        raw_price=_string_or_none(data.get("raw_price") or data.get("price")),
        raw_original_price=_string_or_none(data.get("raw_original_price") or data.get("original_price")),
        raw_discount_rate=_string_or_none(data.get("raw_discount_rate") or data.get("discount_rate")),
        raw_delivery_info=_string_or_none(data.get("raw_delivery_info") or data.get("delivery_info") or data.get("delivery")),
        raw_rating=_string_or_none(data.get("raw_rating") or data.get("rating")),
        raw_review_count=_string_or_none(data.get("raw_review_count") or data.get("review_count")),
        raw_image_url=data.get("raw_image_url") or data.get("image_url"),
        raw_is_sold_out=_string_or_none(data.get("raw_is_sold_out") or data.get("is_sold_out")),
        raw_payload=_json_safe(data.get("raw_payload") or data.get("raw") or data),
        normalization_status=data.get("normalization_status") or "pending",
        crawled_at=data.get("crawled_at") or datetime.now(UTC),
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return _snapshot_to_dict(snapshot)


async def bulk_create_crawled_product_snapshots_db(
    db: AsyncSession,
    products: list[dict],
    *,
    platform: str,
    crawl_keyword: str | None = None,
    crawl_source: str = "search",
) -> list[dict]:
    """검색/크롤링 결과 여러 개를 raw snapshot으로 저장한다."""
    snapshots = []
    for product in products:
        data = {
            **product,
            "platform": product.get("platform") or platform,
            "crawl_keyword": product.get("crawl_keyword") or crawl_keyword,
            "crawl_source": product.get("crawl_source") or crawl_source,
        }
        snapshots.append(await create_crawled_product_snapshot_db(db, data))
    return snapshots


async def get_crawled_product_snapshot_by_id_db(
    db: AsyncSession,
    snapshot_id: int,
) -> Optional[dict]:
    """크롤링 snapshot 단건을 조회한다."""
    snapshot = await db.get(CrawledProductSnapshot, snapshot_id)
    if not snapshot:
        return None
    return _snapshot_to_dict(snapshot)


async def get_crawled_product_snapshots_db(
    db: AsyncSession,
    *,
    platform: str | None = None,
    crawl_keyword: str | None = None,
    normalization_status: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """크롤링 snapshot 목록을 필터링 조회한다."""
    stmt = select(CrawledProductSnapshot).order_by(CrawledProductSnapshot.id.desc())
    if platform:
        stmt = stmt.where(CrawledProductSnapshot.platform == platform)
    if crawl_keyword:
        stmt = stmt.where(CrawledProductSnapshot.crawl_keyword == crawl_keyword)
    if normalization_status:
        stmt = stmt.where(CrawledProductSnapshot.normalization_status == normalization_status)
    if limit:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    return [_snapshot_to_dict(snapshot) for snapshot in result.scalars().all()]


async def update_snapshot_normalization_db(
    db: AsyncSession,
    snapshot_id: int,
    data: dict,
) -> Optional[dict]:
    """정제 결과를 crawled_product_snapshots.normalized_* 컬럼에 업데이트한다."""
    snapshot = await db.get(CrawledProductSnapshot, snapshot_id)
    if not snapshot:
        return None

    allowed_fields = {
        "normalized_name",
        "normalized_brand",
        "normalized_category",
        "normalized_sub_category",
        "normalized_volume",
        "normalized_price",
        "normalized_original_price",
        "normalized_discount_rate",
        "normalized_delivery_type",
        "normalized_rating",
        "normalized_review_count",
        "normalized_is_available",
        "normalization_status",
        "normalization_error",
    }
    for field_name in allowed_fields:
        if field_name in data:
            setattr(snapshot, field_name, data[field_name])

    await db.commit()
    await db.refresh(snapshot)
    return _snapshot_to_dict(snapshot)


async def link_snapshot_to_product_db(
    db: AsyncSession,
    snapshot_id: int,
    product_id: int,
) -> Optional[dict]:
    """정제된 내부 products row와 raw snapshot을 연결한다."""
    snapshot = await db.get(CrawledProductSnapshot, snapshot_id)
    if not snapshot:
        return None

    snapshot.product_id = product_id
    snapshot.normalization_status = snapshot.normalization_status or "normalized"

    await db.commit()
    await db.refresh(snapshot)
    return _snapshot_to_dict(snapshot)
