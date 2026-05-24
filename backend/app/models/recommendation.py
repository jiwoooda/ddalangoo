from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Recommendation(IdMixin, TimestampMixin, Base):
    """사용자 요청 1회에 대해 생성된 추천 결과 묶음이다."""

    __tablename__ = "recommendations"

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
    intent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agent_intents.id"))
    recommendation_type: Mapped[str] = mapped_column(String, nullable=False)
    keyword: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    items: Mapped[list["RecommendationItem"]] = relationship(
        back_populates="recommendation",
        cascade="all, delete-orphan",
    )


class RecommendationItem(IdMixin, Base):
    """사용자에게 제시할 수 있도록 scoring된 상위 추천 후보 snapshot이다."""

    __tablename__ = "recommendation_items"

    recommendation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("recommendations.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    product_option_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("product_options.id"),
    )
    matched_purchase_history_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("purchase_histories.id"),
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    score_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)

    product_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    brand_snapshot: Mapped[str | None] = mapped_column(String)
    category_snapshot: Mapped[str | None] = mapped_column(String)
    option_snapshot: Mapped[str | None] = mapped_column(String)
    platform: Mapped[str | None] = mapped_column(String)
    price_at_recommendation: Mapped[int | None] = mapped_column(Integer)
    original_price_snapshot: Mapped[int | None] = mapped_column(Integer)
    discount_rate_snapshot: Mapped[float | None] = mapped_column(Float)
    delivery_fee: Mapped[int | None] = mapped_column(Integer)
    delivery_info_snapshot: Mapped[str | None] = mapped_column(String)
    rating_snapshot: Mapped[float | None] = mapped_column(Float)
    review_count_snapshot: Mapped[int | None] = mapped_column(Integer)
    product_url_snapshot: Mapped[str | None] = mapped_column(Text)
    image_url_snapshot: Mapped[str | None] = mapped_column(Text)

    is_presented: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_orderable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_block_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    recommendation: Mapped["Recommendation"] = relationship(back_populates="items")
    product = relationship("Product")
    product_option = relationship("ProductOption")
    matched_purchase_history = relationship("PurchaseHistory")
