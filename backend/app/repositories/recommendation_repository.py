from app.mock_data.recommendations import MOCK_RECOMMENDATIONS, MOCK_RECOMMENDATION_ITEMS
from typing import Optional, List
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recommendation import Recommendation, RecommendationItem


def _next_id(rows: list[dict]) -> int:
    return max((row["id"] for row in rows), default=0) + 1

def get_recommendation_by_id(recommendation_id: int) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["id"] == recommendation_id), None)

def get_recommendation_by_conversation_id(conversation_id: int) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["conversation_id"] == conversation_id), None)

def get_items_by_recommendation_id(recommendation_id: int) -> List[dict]:
    return [i for i in MOCK_RECOMMENDATION_ITEMS if i["recommendation_id"] == recommendation_id]

def get_recommendation_by_keyword(keyword: str) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["keyword"] == keyword), None)


def create_recommendation(data: dict) -> dict:
    recommendation = {
        "id": _next_id(MOCK_RECOMMENDATIONS),
        **data,
    }
    MOCK_RECOMMENDATIONS.append(recommendation)
    return recommendation


def create_recommendation_item(recommendation_id: int, data: dict) -> dict:
    item = {
        "id": _next_id(MOCK_RECOMMENDATION_ITEMS),
        "recommendation_id": recommendation_id,
        **data,
    }
    MOCK_RECOMMENDATION_ITEMS.append(item)
    return item


def _recommendation_to_dict(recommendation: Recommendation) -> dict:
    """ORM Recommendation을 기존 응답 매핑이 쓰는 dict 형태로 변환한다."""
    return {
        "id": recommendation.id,
        "conversation_id": recommendation.conversation_id,
        "user_id": recommendation.user_id,
        "intent_id": recommendation.intent_id,
        "recommendation_type": recommendation.recommendation_type,
        "keyword": recommendation.keyword,
        "summary": recommendation.summary,
        "status": recommendation.status,
        "created_at": recommendation.created_at,
        "updated_at": recommendation.updated_at,
    }


def _recommendation_item_to_dict(item: RecommendationItem) -> dict:
    """추천 후보 snapshot ORM을 프론트 매퍼가 이해하는 상품 dict로 변환한다."""
    return {
        "id": item.id,
        "recommendation_item_id": item.id,
        "recommendationItemId": item.id,
        "recommendation_id": item.recommendation_id,
        "product_id": item.product_id or 0,
        "product_name": item.product_name_snapshot,
        "brand": item.brand_snapshot,
        "category": item.category_snapshot,
        "option_text": item.option_snapshot,
        "platform": item.platform,
        "price": item.price_at_recommendation or 0,
        "delivery_fee": item.delivery_fee,
        "delivery_info": item.delivery_info_snapshot,
        "rating": item.rating_snapshot,
        "review_count": item.review_count_snapshot,
        "product_url": item.product_url_snapshot,
        "image_url": item.image_url_snapshot,
        "rank": item.rank,
        "score": item.score,
        "score_detail": item.score_detail,
        "reason": item.reason,
        "is_presented": item.is_presented,
        "presented_at": item.presented_at,
        "is_selected": item.is_selected,
        "is_orderable": item.is_orderable,
        "order_block_reason": item.order_block_reason,
    }


async def get_recommendation_by_conversation_id_db(
    db: AsyncSession,
    conversation_id: int,
) -> Optional[dict]:
    """DB에서 대화에 연결된 추천 묶음을 조회한다."""
    result = await db.execute(
        select(Recommendation).where(Recommendation.conversation_id == conversation_id)
    )
    recommendation = result.scalars().first()
    if not recommendation:
        return None
    return _recommendation_to_dict(recommendation)


async def create_recommendation_db(db: AsyncSession, data: dict) -> dict:
    """DB에 추천 묶음을 생성한다."""
    recommendation = Recommendation(
        conversation_id=data["conversation_id"],
        user_id=data["user_id"],
        intent_id=data.get("intent_id"),
        recommendation_type=data["recommendation_type"],
        keyword=data.get("keyword"),
        summary=data.get("summary"),
        status=data["status"],
    )
    db.add(recommendation)
    await db.commit()
    await db.refresh(recommendation)
    return _recommendation_to_dict(recommendation)


async def create_recommendation_item_db(
    db: AsyncSession,
    recommendation_id: int,
    data: dict,
) -> dict:
    """DB에 추천 후보 snapshot을 생성한다."""
    now = datetime.now(UTC)
    item = RecommendationItem(
        recommendation_id=recommendation_id,
        product_id=data.get("product_id") or None,
        product_option_id=data.get("product_option_id"),
        matched_purchase_history_id=data.get("matched_purchase_history_id"),
        rank=data["rank"],
        score=data.get("score"),
        score_detail=data.get("score_detail"),
        reason=data.get("reason"),
        product_name_snapshot=data["product_name"],
        brand_snapshot=data.get("brand"),
        category_snapshot=data.get("category"),
        option_snapshot=data.get("option_text"),
        platform=data.get("platform"),
        price_at_recommendation=data.get("price"),
        original_price_snapshot=data.get("original_price"),
        discount_rate_snapshot=data.get("discount_rate"),
        delivery_fee=data.get("delivery_fee"),
        delivery_info_snapshot=data.get("delivery_info"),
        rating_snapshot=data.get("rating"),
        review_count_snapshot=data.get("review_count"),
        product_url_snapshot=data.get("product_url"),
        image_url_snapshot=data.get("image_url"),
        is_presented=data.get("is_presented", False),
        presented_at=now if data.get("is_presented") else None,
        is_selected=data.get("is_selected", False),
        is_orderable=data.get("is_orderable", True),
        order_block_reason=data.get("order_block_reason"),
        created_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _recommendation_item_to_dict(item)


async def mark_recommendation_item_presented_db(
    db: AsyncSession,
    recommendation_item_id: int,
) -> Optional[dict]:
    """사용자에게 실제로 제시된 추천 후보를 표시한다."""
    item = await db.get(RecommendationItem, recommendation_item_id)
    if not item:
        return None

    item.is_presented = True
    if item.presented_at is None:
        item.presented_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(item)
    return _recommendation_item_to_dict(item)


async def mark_recommendation_item_selected_db(
    db: AsyncSession,
    recommendation_item_id: int,
) -> Optional[dict]:
    """
    최종 선택된 추천 후보를 표시한다.

    같은 recommendation 안에서는 하나만 selected=true가 되도록 기존 선택을 해제한다.
    """
    item = await db.get(RecommendationItem, recommendation_item_id)
    if not item:
        return None

    result = await db.execute(
        select(RecommendationItem).where(
            RecommendationItem.recommendation_id == item.recommendation_id
        )
    )
    for sibling in result.scalars().all():
        sibling.is_selected = sibling.id == item.id

    item.is_presented = True
    if item.presented_at is None:
        item.presented_at = datetime.now(UTC)

    recommendation = await db.get(Recommendation, item.recommendation_id)
    if recommendation:
        recommendation.status = "selected"

    await db.commit()
    await db.refresh(item)
    return _recommendation_item_to_dict(item)
