from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import user_preference_feedback_repository


async def create_user_preference_feedback_db(
    db: AsyncSession,
    *,
    user_id: int,
    feedback_type: str,
    feedback_text: str,
    conversation_id: int | None = None,
    message_id: int | None = None,
    recommendation_item_id: int | None = None,
    product_id: int | None = None,
    product_option_id: int | None = None,
    feedback_target: str | None = None,
    feedback_value: str | None = None,
    confidence: float | None = None,
    is_long_term_memory_candidate: bool = False,
    applied_scope: str | None = None,
    is_applied: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    명시적 사용자 피드백을 저장한다.

    이번 단계에서는 LangGraph 자동 추출과 연결하지 않고, 이미 구조화된 피드백을
    안정적으로 저장하는 경계만 제공한다.
    """
    normalized_text = feedback_text.strip()
    if not normalized_text:
        raise ValueError("feedback_text는 비어 있을 수 없습니다.")
    normalized_type = feedback_type.strip()
    if not normalized_type:
        raise ValueError("feedback_type은 비어 있을 수 없습니다.")

    return await user_preference_feedback_repository.create_user_preference_feedback_db(
        db,
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "recommendation_item_id": recommendation_item_id,
            "product_id": product_id,
            "product_option_id": product_option_id,
            "feedback_type": normalized_type,
            "feedback_target": feedback_target,
            "feedback_value": feedback_value,
            "feedback_text": normalized_text,
            "confidence": confidence,
            "is_long_term_memory_candidate": is_long_term_memory_candidate,
            "applied_scope": applied_scope,
            "is_applied": is_applied,
            "metadata": metadata,
        },
    )


async def get_user_preference_feedbacks_db(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int | None = None,
    recommendation_item_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """사용자 명시 피드백 목록을 조회한다."""
    return await user_preference_feedback_repository.get_user_preference_feedbacks_db(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        recommendation_item_id=recommendation_item_id,
        limit=limit,
    )
