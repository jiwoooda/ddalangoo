from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin


class PurchaseHistory(IdMixin, CreatedAtMixin, Base):
    """구매 완료 후 재구매 판단 근거가 되는 과거 구매 기록이다."""

    __tablename__ = "purchase_histories"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    product_option_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("product_options.id"),
    )
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
    )
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("orders.id"))
    payment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("payments.id"))

    external_order_id: Mapped[str | None] = mapped_column(String)
    external_product_order_id: Mapped[str | None] = mapped_column(String)
    platform: Mapped[str | None] = mapped_column(String)
    keyword: Mapped[str | None] = mapped_column(String)

    product_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    option_snapshot: Mapped[str | None] = mapped_column(String)
    brand_snapshot: Mapped[str | None] = mapped_column(String)
    category_snapshot: Mapped[str | None] = mapped_column(String)
    price_at_purchase: Mapped[int] = mapped_column(Integer, nullable=False)
    product_url_snapshot: Mapped[str | None] = mapped_column(Text)
    selected_options: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price: Mapped[int] = mapped_column(Integer, nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    satisfaction: Mapped[int | None] = mapped_column(Integer)
    memo: Mapped[str | None] = mapped_column(Text)

    user = relationship("User")
    product = relationship("Product")
    product_option = relationship("ProductOption")
