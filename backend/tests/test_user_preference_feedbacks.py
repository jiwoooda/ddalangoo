import asyncio
from datetime import UTC, datetime

import pytest

from app.models import Base
from app.services import user_preference_feedback_service


class FakeAsyncSession:
    """repository 저장 경계를 확인하기 위한 최소 AsyncSession 대역이다."""

    def __init__(self):
        self.added = None
        self.committed = False
        self.refreshed = False

    def add(self, row):
        self.added = row

    async def commit(self):
        self.committed = True

    async def refresh(self, row):
        self.refreshed = True
        row.id = 10
        row.created_at = datetime.now(UTC)


def test_user_preference_feedback_model_columns():
    """ORM metadata에 user_preference_feedbacks 테이블과 핵심 컬럼이 등록되어야 한다."""
    table = Base.metadata.tables["user_preference_feedbacks"]

    assert table.c.user_id.nullable is False
    assert table.c.feedback_type.nullable is False
    assert table.c.feedback_text.nullable is False
    assert table.c.metadata.nullable is True
    assert "conversations.id" in {str(fk.column) for fk in table.c.conversation_id.foreign_keys}
    assert "recommendation_items.id" in {
        str(fk.column) for fk in table.c.recommendation_item_id.foreign_keys
    }


def test_create_user_preference_feedback_service_stores_row():
    """service → repository → DB session add/commit/refresh 저장 흐름을 검증한다."""
    db = FakeAsyncSession()

    result = asyncio.run(
        user_preference_feedback_service.create_user_preference_feedback_db(
            db,
            user_id=1,
            conversation_id=2,
            message_id=3,
            recommendation_item_id=4,
            product_id=5,
            feedback_type="negative",
            feedback_target="price",
            feedback_value="too_expensive",
            feedback_text="아니 그건 너무 비싸",
            confidence=0.92,
            is_long_term_memory_candidate=True,
            applied_scope="user",
            metadata={"source": "test"},
        )
    )

    assert db.committed is True
    assert db.refreshed is True
    assert result["id"] == 10
    assert result["user_id"] == 1
    assert result["conversation_id"] == 2
    assert result["recommendation_item_id"] == 4
    assert result["feedback_type"] == "negative"
    assert result["feedback_target"] == "price"
    assert result["feedback_value"] == "too_expensive"
    assert result["feedback_text"] == "아니 그건 너무 비싸"
    assert result["is_long_term_memory_candidate"] is True
    assert result["is_applied"] is False
    assert result["metadata"] == {"source": "test"}


def test_create_user_preference_feedback_rejects_empty_text():
    """빈 피드백 원문은 저장하지 않는다."""
    with pytest.raises(ValueError):
        asyncio.run(
            user_preference_feedback_service.create_user_preference_feedback_db(
                FakeAsyncSession(),
                user_id=1,
                feedback_type="negative",
                feedback_text="  ",
            )
        )
