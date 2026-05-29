from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin


class UserPreferenceCache(IdMixin, TimestampMixin, Base):
    """memory_agent가 재사용하는 사용자 선호도 캐시 테이블이다."""

    __tablename__ = "user_preference_cache"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "preference_type",
            "keywords_key",
            name="uq_user_preference_cache_key",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    preference_type: Mapped[str] = mapped_column(String, nullable=False)
    keywords_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    preference_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserPreferenceFeedback(IdMixin, CreatedAtMixin, Base):
    """사용자가 명시적으로 말한 선호/비선호 피드백 원문과 구조화 결과를 저장한다."""

    __tablename__ = "user_preference_feedbacks"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        index=True,
    )
    message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("conversation_messages.id"),
    )
    recommendation_item_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("recommendation_items.id"),
        index=True,
    )
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    product_option_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("product_options.id"),
    )
    feedback_type: Mapped[str] = mapped_column(String, nullable=False)
    feedback_target: Mapped[str | None] = mapped_column(String)
    feedback_value: Mapped[str | None] = mapped_column(String)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    is_long_term_memory_candidate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    applied_scope: Mapped[str | None] = mapped_column(String)
    is_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
