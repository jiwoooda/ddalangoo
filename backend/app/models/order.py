from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin


class Cart(IdMixin, TimestampMixin, Base):
    """결제 전 사용자가 담아둔 상품 묶음이다."""

    __tablename__ = "carts"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"))
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
    )


class CartItem(IdMixin, TimestampMixin, Base):
    """장바구니에 담긴 개별 상품과 담을 당시 snapshot이다."""

    __tablename__ = "cart_items"

    cart_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("carts.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    product_option_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_options.id"))
    recommendation_item_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("recommendation_items.id"),
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    option_snapshot: Mapped[str | None] = mapped_column(String)

    cart: Mapped["Cart"] = relationship(back_populates="items")
    product = relationship("Product")
    product_option = relationship("ProductOption")
    recommendation_item = relationship("RecommendationItem")


class CheckoutSession(IdMixin, TimestampMixin, Base):
    """장바구니를 실제 주문/결제로 넘기기 전의 결제 준비 상태다."""

    __tablename__ = "checkout_sessions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"))
    cart_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("carts.id"), nullable=False)
    delivery_address_snapshot: Mapped[str | None] = mapped_column(Text)
    address_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_product_price: Mapped[int | None] = mapped_column(Integer)
    delivery_fee: Mapped[int | None] = mapped_column(Integer)
    total_expected_amount: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, index=True)

    cart = relationship("Cart")


class Order(IdMixin, TimestampMixin, Base):
    """사용자 최종 확인 이후 생성되는 주문 전체 정보다."""

    __tablename__ = "orders"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"))
    cart_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("carts.id"))
    checkout_session_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("checkout_sessions.id"))
    recommendation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("recommendations.id"))
    shipping_address_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user_addresses.id"))

    recipient_name_snapshot: Mapped[str | None] = mapped_column(String)
    recipient_phone_snapshot: Mapped[str | None] = mapped_column(String)
    shipping_address_snapshot: Mapped[str | None] = mapped_column(Text)
    delivery_request_snapshot: Mapped[str | None] = mapped_column(Text)

    platform: Mapped[str] = mapped_column(String, nullable=False)
    order_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    total_product_price: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_fee: Mapped[int | None] = mapped_column(Integer)
    total_payment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String, index=True)
    failed_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(IdMixin, CreatedAtMixin, Base):
    """주문에 포함된 개별 상품과 주문 당시 상품 snapshot이다."""

    __tablename__ = "order_items"

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    product_option_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_options.id"))
    recommendation_item_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("recommendation_items.id"),
    )
    product_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    option_snapshot: Mapped[str | None] = mapped_column(String)
    product_url_snapshot: Mapped[str | None] = mapped_column(Text)
    selected_options: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    external_product_order_id: Mapped[str | None] = mapped_column(String)

    order: Mapped["Order"] = relationship(back_populates="items")
    product = relationship("Product")
    product_option = relationship("ProductOption")
    recommendation_item = relationship("RecommendationItem")


class Payment(IdMixin, TimestampMixin, Base):
    """주문과 분리해서 결제 상태, 외부 결제 ID, 실패 사유를 저장한다."""

    __tablename__ = "payments"

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False, index=True)
    payment_provider: Mapped[str] = mapped_column(String, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String)
    payment_status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    external_payment_id: Mapped[str | None] = mapped_column(String)
    approval_number: Mapped[str | None] = mapped_column(String)
    payment_url: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    order = relationship("Order")


class NaverOrderMapping(IdMixin, TimestampMixin, Base):
    """내부 주문/결제 ID와 네이버페이 주문/결제 식별자를 연결한다."""

    __tablename__ = "naver_order_mappings"

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False, index=True)
    payment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("payments.id"))
    naver_order_id: Mapped[str | None] = mapped_column(String)
    naver_product_order_id: Mapped[str | None] = mapped_column(String)
    naver_payment_id: Mapped[str | None] = mapped_column(String)
    naver_pay_order_key: Mapped[str | None] = mapped_column(String)
    naver_status: Mapped[str | None] = mapped_column(String)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order = relationship("Order")
    payment = relationship("Payment")
