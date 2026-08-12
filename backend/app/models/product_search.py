from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class ProductSearchExecution(IdMixin, TimestampMixin, Base):
    """Android Accessibility 기반 플랫폼 상품 검색 실행 상태를 저장한다."""

    __tablename__ = "product_search_executions"

    search_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    preferred_platform: Mapped[str | None] = mapped_column(String)
    platform_queue: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    current_platform: Mapped[str | None] = mapped_column(String)
    current_platform_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    products_by_platform: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    merged_products: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation = relationship("Conversation")
    user = relationship("User")
