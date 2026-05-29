from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


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
