from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preference import UserPreferenceFeedback


def _feedback_to_dict(feedback: UserPreferenceFeedback) -> dict[str, Any]:
    """ORM UserPreferenceFeedback을 service/API에서 쓰기 쉬운 dict로 변환한다."""
    return {
        "id": feedback.id,
        "user_id": feedback.user_id,
        "conversation_id": feedback.conversation_id,
        "message_id": feedback.message_id,
        "recommendation_item_id": feedback.recommendation_item_id,
        "product_id": feedback.product_id,
        "product_option_id": feedback.product_option_id,
        "feedback_type": feedback.feedback_type,
        "feedback_target": feedback.feedback_target,
        "feedback_value": feedback.feedback_value,
        "feedback_text": feedback.feedback_text,
        "confidence": feedback.confidence,
        "is_long_term_memory_candidate": feedback.is_long_term_memory_candidate,
        "applied_scope": feedback.applied_scope,
        "is_applied": feedback.is_applied,
        "metadata": feedback.metadata_,
        "created_at": feedback.created_at,
    }


async def create_user_preference_feedback_db(
    db: AsyncSession,
    data: dict[str, Any],
) -> dict[str, Any]:
    """명시적 선호/비선호 피드백을 DB에 저장한다."""
    feedback = UserPreferenceFeedback(
        user_id=data["user_id"],
        conversation_id=data.get("conversation_id"),
        message_id=data.get("message_id"),
        recommendation_item_id=data.get("recommendation_item_id"),
        product_id=data.get("product_id"),
        product_option_id=data.get("product_option_id"),
        feedback_type=data["feedback_type"],
        feedback_target=data.get("feedback_target"),
        feedback_value=data.get("feedback_value"),
        feedback_text=data["feedback_text"],
        confidence=data.get("confidence"),
        is_long_term_memory_candidate=bool(data.get("is_long_term_memory_candidate", False)),
        applied_scope=data.get("applied_scope"),
        is_applied=bool(data.get("is_applied", False)),
        metadata_=data.get("metadata"),
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return _feedback_to_dict(feedback)


async def get_user_preference_feedbacks_db(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int | None = None,
    recommendation_item_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """사용자 피드백 목록을 최신순으로 조회한다."""
    stmt = select(UserPreferenceFeedback).where(UserPreferenceFeedback.user_id == user_id)
    if conversation_id is not None:
        stmt = stmt.where(UserPreferenceFeedback.conversation_id == conversation_id)
    if recommendation_item_id is not None:
        stmt = stmt.where(UserPreferenceFeedback.recommendation_item_id == recommendation_item_id)
    stmt = stmt.order_by(UserPreferenceFeedback.created_at.desc(), UserPreferenceFeedback.id.desc())
    if limit:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    return [_feedback_to_dict(row) for row in result.scalars().all()]
