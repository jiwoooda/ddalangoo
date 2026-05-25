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

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin


class CrawledProductSnapshot(IdMixin, CreatedAtMixin, Base):
    """외부 플랫폼에서 관찰한 raw 상품 데이터와 정제 결과를 보존한다."""

    __tablename__ = "crawled_product_snapshots"

    platform: Mapped[str] = mapped_column(String, nullable=False, index=True)
    external_product_id: Mapped[str | None] = mapped_column(String)
    external_product_url: Mapped[str | None] = mapped_column(Text)
    crawl_keyword: Mapped[str | None] = mapped_column(String)
    crawl_source: Mapped[str | None] = mapped_column(String)

    raw_product_name: Mapped[str] = mapped_column(Text, nullable=False)
    raw_brand: Mapped[str | None] = mapped_column(String)
    raw_category: Mapped[str | None] = mapped_column(String)
    raw_price: Mapped[str | None] = mapped_column(String)
    raw_original_price: Mapped[str | None] = mapped_column(String)
    raw_discount_rate: Mapped[str | None] = mapped_column(String)
    raw_delivery_info: Mapped[str | None] = mapped_column(String)
    raw_rating: Mapped[str | None] = mapped_column(String)
    raw_review_count: Mapped[str | None] = mapped_column(String)
    raw_image_url: Mapped[str | None] = mapped_column(Text)
    raw_is_sold_out: Mapped[str | None] = mapped_column(String)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    normalized_name: Mapped[str | None] = mapped_column(String)
    normalized_brand: Mapped[str | None] = mapped_column(String)
    normalized_category: Mapped[str | None] = mapped_column(String)
    normalized_sub_category: Mapped[str | None] = mapped_column(String)
    normalized_volume: Mapped[str | None] = mapped_column(String)
    normalized_price: Mapped[int | None] = mapped_column(Integer)
    normalized_original_price: Mapped[int | None] = mapped_column(Integer)
    normalized_discount_rate: Mapped[float | None] = mapped_column(Float)
    normalized_delivery_type: Mapped[str | None] = mapped_column(String)
    normalized_rating: Mapped[float | None] = mapped_column(Float)
    normalized_review_count: Mapped[int | None] = mapped_column(Integer)
    normalized_is_available: Mapped[bool | None] = mapped_column(Boolean)

    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    normalization_status: Mapped[str | None] = mapped_column(String)
    normalization_error: Mapped[str | None] = mapped_column(Text)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Product(IdMixin, TimestampMixin, Base):
    """정제된 내부 상품 기본 정보 테이블이다."""

    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(String)
    brand: Mapped[str | None] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sub_category: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)

    image_url: Mapped[str | None] = mapped_column(Text)
    current_price: Mapped[int | None] = mapped_column(Integer)
    original_price: Mapped[int | None] = mapped_column(Integer)
    discount_rate: Mapped[float | None] = mapped_column(Float)
    delivery_type: Mapped[str | None] = mapped_column(String)
    current_delivery_info: Mapped[str | None] = mapped_column(String)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # crawled_product_snapshots.product_id와 순환 참조가 있어 migration 생성 순서에 주의한다.
    last_crawled_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "crawled_product_snapshots.id",
            use_alter=True,
            name="fk_products_last_crawled_snapshot_id",
        ),
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    options: Mapped[list["ProductOption"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    external_mappings: Mapped[list["ExternalProductMapping"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class ProductOption(IdMixin, TimestampMixin, Base):
    """상품의 용량, 구성, 추가 가격 같은 옵션 정보를 저장한다."""

    __tablename__ = "product_options"

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    option_name: Mapped[str | None] = mapped_column(String)
    option_value: Mapped[str | None] = mapped_column(String)
    volume: Mapped[str | None] = mapped_column(String)
    additional_price: Mapped[int | None] = mapped_column(Integer)
    stock_quantity: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    product: Mapped["Product"] = relationship(back_populates="options")


class ExternalProductMapping(IdMixin, TimestampMixin, Base):
    """내부 상품과 외부 플랫폼 상품 식별자를 연결한다."""

    __tablename__ = "external_product_mappings"

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    product_option_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("product_options.id"),
    )
    platform: Mapped[str] = mapped_column(String, nullable=False, index=True)
    external_product_id: Mapped[str | None] = mapped_column(String)
    external_option_id: Mapped[str | None] = mapped_column(String)
    external_product_url: Mapped[str | None] = mapped_column(Text)
    external_product_url_hash: Mapped[str | None] = mapped_column(String)
    mall_name: Mapped[str | None] = mapped_column(String)
    seller_name: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped["Product"] = relationship(back_populates="external_mappings")
    product_option: Mapped["ProductOption | None"] = relationship()
