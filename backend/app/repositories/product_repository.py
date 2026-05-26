from app.mock_data.products import MOCK_PRODUCTS, MOCK_PRODUCT_OPTIONS, MOCK_NAVER_PRODUCT_MAPPINGS
from typing import Optional, List
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import CrawledProductSnapshot, ExternalProductMapping, Product
from app.utils.product_url_contract import (
    canonical_product_url_for_platform,
    fallback_product_fingerprint,
    is_search_like_url,
    stable_hash,
)

def get_all_products() -> List[dict]:
    return MOCK_PRODUCTS

def get_product_by_id(product_id: int) -> Optional[dict]:
    return next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)

def get_options_by_product_id(product_id: int) -> List[dict]:
    return [o for o in MOCK_PRODUCT_OPTIONS if o["product_id"] == product_id]

def get_naver_mappings_by_product_id(product_id: int) -> List[dict]:
    return [m for m in MOCK_NAVER_PRODUCT_MAPPINGS if m["product_id"] == product_id]


def external_product_url_hash(product_url: str | None) -> str | None:
    """외부 URL이 있을 때 보조 식별값으로 쓸 sha256 hash를 만든다."""
    return stable_hash(product_url)


def _raw_metadata(candidate: dict, *, execution_url: str | None, canonical_product_url: str | None, identity_strategy: str) -> dict:
    """외부 매핑 metadata에 원본 payload와 URL 계약 정보를 함께 저장한다."""
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    return {
        **raw,
        "execution_url": execution_url,
        "canonical_product_url": canonical_product_url,
        "identity_strategy": identity_strategy,
    }


def _candidate_identity_contract(candidate: dict, product_name: str) -> dict:
    """
    외부 상품 매핑에 사용할 식별 계약을 계산한다.

    검색 URL은 execution_url로만 남기고, external_product_url_hash에는 /goods/ canonical
    URL hash 또는 후보 fingerprint만 들어가게 한다.
    """
    platform = candidate.get("platform") or "unknown"
    execution_url = candidate.get("execution_url") or candidate.get("product_url") or candidate.get("url")
    canonical_product_url = (
        candidate.get("canonical_product_url")
        or canonical_product_url_for_platform(
            platform,
            candidate.get("external_product_url"),
            candidate.get("product_url"),
            candidate.get("url"),
        )
    )
    canonical_url_hash = external_product_url_hash(canonical_product_url)
    fallback_hash = fallback_product_fingerprint(
        platform=platform,
        product_name=product_name,
        price=candidate.get("price") or candidate.get("current_price"),
        image_url=candidate.get("image_url"),
    )
    return {
        "platform": platform,
        "raw_url": candidate.get("external_product_url") or candidate.get("product_url") or candidate.get("url"),
        "execution_url": execution_url,
        "canonical_product_url": canonical_product_url,
        "identity_hash": canonical_url_hash or fallback_hash,
        "identity_strategy": "canonical_url" if canonical_url_hash else "fallback_fingerprint",
    }


def _is_legacy_search_url_mapping(mapping: ExternalProductMapping | None) -> bool:
    """이전 배포에서 검색 URL hash로 생성된 매핑은 상품 식별 매핑으로 재사용하지 않는다."""
    if not mapping:
        return False
    return (mapping.platform or "").lower() == "kurly" and is_search_like_url(mapping.external_product_url)


def _product_to_dict(product: Product) -> dict:
    """ORM Product를 기존 서비스 응답 매핑용 dict로 변환한다."""
    return {
        "id": product.id,
        "name": product.name,
        "normalized_name": product.normalized_name,
        "brand": product.brand,
        "category": product.category,
        "sub_category": product.sub_category,
        "description": product.description,
        "image_url": product.image_url,
        "current_price": product.current_price,
        "original_price": product.original_price,
        "discount_rate": product.discount_rate,
        "delivery_type": product.delivery_type,
        "current_delivery_info": product.current_delivery_info,
        "rating": product.rating,
        "review_count": product.review_count,
        "is_available": product.is_available,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


def _mapping_to_dict(mapping: ExternalProductMapping) -> dict:
    """ORM ExternalProductMapping을 API 응답용 dict로 변환한다."""
    return {
        "id": mapping.id,
        "product_id": mapping.product_id,
        "product_option_id": mapping.product_option_id,
        "platform": mapping.platform,
        "external_product_id": mapping.external_product_id,
        "external_option_id": mapping.external_option_id,
        "external_product_url": mapping.external_product_url,
        "external_product_url_hash": mapping.external_product_url_hash,
        "mall_name": mapping.mall_name,
        "seller_name": mapping.seller_name,
        "metadata": mapping.metadata_json,
        "last_synced_at": mapping.last_synced_at,
    }


async def get_all_products_db(
    db: AsyncSession,
    keyword: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """DB 상품 목록을 조회한다."""
    stmt = select(Product).order_by(Product.id.desc())
    if keyword:
        stmt = stmt.where(Product.name.ilike(f"%{keyword}%"))
    if category:
        stmt = stmt.where(Product.category == category)
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return [_product_to_dict(product) for product in result.scalars().all()]


async def get_product_by_id_db(db: AsyncSession, product_id: int) -> Optional[dict]:
    """DB에서 상품 단건을 조회한다."""
    product = await db.get(Product, product_id)
    if not product:
        return None
    return _product_to_dict(product)


async def get_external_mappings_by_product_id_db(
    db: AsyncSession,
    product_id: int,
) -> list[dict]:
    """상품에 연결된 외부 플랫폼 매핑을 조회한다."""
    result = await db.execute(
        select(ExternalProductMapping).where(ExternalProductMapping.product_id == product_id)
    )
    return [_mapping_to_dict(mapping) for mapping in result.scalars().all()]


async def search_product_candidates_db(
    db: AsyncSession,
    keywords: list[str],
    *,
    limit: int = 5,
) -> list[dict]:
    """
    DB products 후보 pool에서 추천 후보를 조회한다.

    외부 검색이 실패했거나, 크롤링으로 쌓아둔 임시 상품 카탈로그를 먼저 보고 싶을 때 사용한다.
    """
    normalized_keywords = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
    if not normalized_keywords:
        return []

    conditions = []
    for keyword in normalized_keywords:
        pattern = f"%{keyword}%"
        conditions.extend([
            Product.name.ilike(pattern),
            Product.normalized_name.ilike(pattern),
            Product.brand.ilike(pattern),
            Product.category.ilike(pattern),
            Product.sub_category.ilike(pattern),
        ])

    result = await db.execute(
        select(Product)
        .where(Product.is_available.is_(True))
        .where(or_(*conditions))
        .order_by(Product.review_count.desc().nullslast(), Product.rating.desc().nullslast())
        .limit(limit)
    )
    products = result.scalars().all()

    candidates = []
    for product in products:
        product_dict = _product_to_dict(product)
        mappings = await get_external_mappings_by_product_id_db(db, product.id)
        primary_mapping = next(
            (
                mapping
                for mapping in mappings
                if not (
                    (mapping.get("platform") or "").lower() == "kurly"
                    and is_search_like_url(mapping.get("external_product_url"))
                )
            ),
            mappings[0] if mappings else {},
        )
        is_legacy_primary = (
            (primary_mapping.get("platform") or "").lower() == "kurly"
            and is_search_like_url(primary_mapping.get("external_product_url"))
        )
        mapping_metadata = primary_mapping.get("metadata") if isinstance(primary_mapping.get("metadata"), dict) else {}
        execution_url = (
            mapping_metadata.get("execution_url")
            if is_legacy_primary
            else primary_mapping.get("external_product_url") or mapping_metadata.get("execution_url")
        )
        canonical_product_url = None if is_legacy_primary else primary_mapping.get("external_product_url")
        candidates.append({
            "product_id": product_dict["id"],
            "product_name": product_dict["name"],
            "name": product_dict["name"],
            "brand": product_dict.get("brand"),
            "category": product_dict.get("category"),
            "price": product_dict.get("current_price") or 0,
            "original_price": product_dict.get("original_price"),
            "discount_rate": product_dict.get("discount_rate"),
            "delivery_type": product_dict.get("delivery_type"),
            "delivery_info": product_dict.get("current_delivery_info"),
            "rating": product_dict.get("rating"),
            "review_count": product_dict.get("review_count"),
            "image_url": product_dict.get("image_url"),
            "product_url": execution_url,
            "execution_url": execution_url,
            "canonical_product_url": canonical_product_url,
            "platform": primary_mapping.get("platform"),
            "delivery_fee": None,
            "is_sold_out": not bool(product_dict.get("is_available")),
            "is_orderable": bool(execution_url),
            "order_block_reason": None if execution_url else "execution_url_missing",
            "raw": {
                "source": "products_pool",
                "product": product_dict,
                "external_mapping": primary_mapping,
            },
        })

    return candidates


async def upsert_product_from_candidate_db(
    db: AsyncSession,
    candidate: dict,
    default_category: str = "unknown",
) -> dict:
    """
    추천/검색 후보를 내부 products와 external_product_mappings에 반영한다.

    공식 API가 없는 MVP에서는 검색 후보 snapshot을 정제 상품 pool로 사용한다.
    """
    product_name = candidate.get("product_name") or candidate.get("name")
    if not product_name:
        raise ValueError("product_name이 없는 후보는 products에 저장할 수 없습니다.")

    identity = _candidate_identity_contract(candidate, product_name)
    platform = identity["platform"]
    execution_url = identity["execution_url"]
    canonical_product_url = identity["canonical_product_url"]
    identity_hash = identity["identity_hash"]
    identity_strategy = identity["identity_strategy"]

    print(
        "[product_url_contract:mapping] "
        f"platform={platform} "
        f"raw_url={identity.get('raw_url')} "
        f"execution_url={execution_url} "
        f"canonical_product_url={canonical_product_url} "
        f"is_search_url={is_search_like_url(identity.get('raw_url'))} "
        f"mapping_key_type={identity_strategy} "
        f"mapping_key={identity_hash}"
    )

    product: Product | None = None
    if candidate.get("external_product_id"):
        mapping_result = await db.execute(
            select(ExternalProductMapping).where(
                ExternalProductMapping.platform == platform,
                ExternalProductMapping.external_product_id == candidate.get("external_product_id"),
            )
        )
        mapping = mapping_result.scalars().first()
        if mapping and _is_legacy_search_url_mapping(mapping):
            print(
                "[product_url_contract:mapping] "
                f"ignored_legacy_search_mapping id={mapping.id} "
                f"hash={mapping.external_product_url_hash} "
                f"url={mapping.external_product_url}"
            )
            mapping = None
        if mapping:
            product = await db.get(Product, mapping.product_id)

    if product is None and identity_hash:
        mapping_result = await db.execute(
            select(ExternalProductMapping).where(
                ExternalProductMapping.platform == platform,
                ExternalProductMapping.external_product_url_hash == identity_hash,
            )
        )
        mapping = mapping_result.scalars().first()
        if mapping and _is_legacy_search_url_mapping(mapping):
            print(
                "[product_url_contract:mapping] "
                f"ignored_legacy_search_mapping id={mapping.id} "
                f"hash={mapping.external_product_url_hash} "
                f"url={mapping.external_product_url}"
            )
            mapping = None
        if mapping:
            product = await db.get(Product, mapping.product_id)

    if product is None:
        product_result = await db.execute(
            select(Product).where(
                Product.name == product_name,
                Product.category == (candidate.get("category") or default_category),
            )
        )
        product = product_result.scalars().first()

    if product is None:
        product = Product(
            name=product_name,
            normalized_name=candidate.get("normalized_name"),
            brand=candidate.get("brand"),
            category=candidate.get("category") or default_category,
            sub_category=candidate.get("sub_category"),
            image_url=candidate.get("image_url"),
            current_price=candidate.get("price") or candidate.get("current_price"),
            original_price=candidate.get("original_price"),
            discount_rate=candidate.get("discount_rate"),
            delivery_type=candidate.get("delivery_type"),
            current_delivery_info=candidate.get("delivery_info") or candidate.get("delivery"),
            rating=candidate.get("rating"),
            review_count=candidate.get("review_count"),
            is_available=not bool(candidate.get("is_sold_out")),
            last_crawled_at=datetime.now(UTC),
        )
        db.add(product)
        await db.flush()
    else:
        product.brand = candidate.get("brand") or product.brand
        product.image_url = candidate.get("image_url") or product.image_url
        product.current_price = candidate.get("price") or candidate.get("current_price") or product.current_price
        product.original_price = candidate.get("original_price") or product.original_price
        product.discount_rate = candidate.get("discount_rate") or product.discount_rate
        product.delivery_type = candidate.get("delivery_type") or product.delivery_type
        product.current_delivery_info = (
            candidate.get("delivery_info")
            or candidate.get("delivery")
            or product.current_delivery_info
        )
        product.rating = candidate.get("rating") if candidate.get("rating") is not None else product.rating
        product.review_count = (
            candidate.get("review_count")
            if candidate.get("review_count") is not None
            else product.review_count
        )
        product.is_available = not bool(candidate.get("is_sold_out"))
        product.last_crawled_at = datetime.now(UTC)

    if identity_hash or candidate.get("external_product_id"):
        mapping_lookup = select(ExternalProductMapping).where(
            ExternalProductMapping.platform == platform,
        )
        if candidate.get("external_product_id"):
            mapping_lookup = mapping_lookup.where(
                ExternalProductMapping.external_product_id == candidate.get("external_product_id"),
            )
        else:
            mapping_lookup = mapping_lookup.where(
                ExternalProductMapping.external_product_url_hash == identity_hash,
            )
        mapping_result = await db.execute(mapping_lookup)
        mapping = mapping_result.scalars().first()
        if mapping and _is_legacy_search_url_mapping(mapping):
            print(
                "[product_url_contract:mapping] "
                f"ignored_legacy_search_mapping id={mapping.id} "
                f"hash={mapping.external_product_url_hash} "
                f"url={mapping.external_product_url}"
            )
            mapping = None
        if mapping is None:
            mapping = ExternalProductMapping(
                product_id=product.id,
                platform=platform,
                external_product_id=candidate.get("external_product_id"),
                external_option_id=candidate.get("external_option_id"),
                external_product_url=canonical_product_url,
                external_product_url_hash=identity_hash,
                mall_name=candidate.get("mall_name"),
                seller_name=candidate.get("seller_name"),
                metadata_json=_raw_metadata(
                    candidate,
                    execution_url=execution_url,
                    canonical_product_url=canonical_product_url,
                    identity_strategy=identity_strategy,
                ),
                last_synced_at=datetime.now(UTC),
            )
            db.add(mapping)
        else:
            mapping.product_id = product.id
            mapping.external_product_id = candidate.get("external_product_id") or mapping.external_product_id
            mapping.external_option_id = candidate.get("external_option_id") or mapping.external_option_id
            mapping.external_product_url = canonical_product_url or mapping.external_product_url
            mapping.mall_name = candidate.get("mall_name") or mapping.mall_name
            mapping.seller_name = candidate.get("seller_name") or mapping.seller_name
            mapping.metadata_json = _raw_metadata(
                candidate,
                execution_url=execution_url,
                canonical_product_url=canonical_product_url,
                identity_strategy=identity_strategy,
            ) or mapping.metadata_json
            mapping.last_synced_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(product)
    return _product_to_dict(product)


async def upsert_product_from_snapshot_db(
    db: AsyncSession,
    snapshot: dict,
    default_category: str = "unknown",
) -> dict:
    """
    crawled_product_snapshots row를 기반으로 products/external_product_mappings를 upsert한다.

    정제값이 있으면 normalized_*를 우선 사용하고, 없으면 raw_* 원본값을 fallback으로 사용한다.
    """
    raw_payload = snapshot.get("raw_payload") if isinstance(snapshot.get("raw_payload"), dict) else {}
    candidate = {
        "product_name": snapshot.get("normalized_name") or snapshot.get("raw_product_name"),
        "normalized_name": snapshot.get("normalized_name"),
        "brand": snapshot.get("normalized_brand") or snapshot.get("raw_brand"),
        "category": snapshot.get("normalized_category") or snapshot.get("raw_category") or default_category,
        "sub_category": snapshot.get("normalized_sub_category"),
        "price": snapshot.get("normalized_price"),
        "original_price": snapshot.get("normalized_original_price"),
        "discount_rate": snapshot.get("normalized_discount_rate"),
        "delivery_type": snapshot.get("normalized_delivery_type"),
        "delivery_info": snapshot.get("raw_delivery_info"),
        "rating": snapshot.get("normalized_rating"),
        "review_count": snapshot.get("normalized_review_count"),
        "image_url": snapshot.get("raw_image_url"),
        "is_sold_out": (
            snapshot.get("normalized_is_available") is False
            or str(snapshot.get("raw_is_sold_out") or "").lower() in {"true", "sold_out", "품절"}
        ),
        "platform": snapshot.get("platform"),
        "external_product_id": snapshot.get("external_product_id"),
        "canonical_product_url": snapshot.get("external_product_url"),
        "execution_url": raw_payload.get("execution_url") or snapshot.get("external_product_url"),
        "product_url": raw_payload.get("execution_url") or snapshot.get("external_product_url"),
        "raw": raw_payload,
    }
    product = await upsert_product_from_candidate_db(
        db,
        candidate,
        default_category=default_category,
    )

    snapshot_id = snapshot.get("id")
    if snapshot_id:
        snapshot_model = await db.get(CrawledProductSnapshot, snapshot_id)
        if snapshot_model:
            snapshot_model.product_id = product["id"]
            snapshot_model.normalization_status = "normalized"

            product_model = await db.get(Product, product["id"])
            if product_model:
                product_model.last_crawled_snapshot_id = snapshot_id
                product_model.last_crawled_at = snapshot.get("crawled_at") or datetime.now(UTC)

            await db.commit()

    return product
