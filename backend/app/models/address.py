from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class UserAddress(IdMixin, TimestampMixin, Base):
    """사용자의 배송지 정보와 주소 별칭을 저장한다."""

    __tablename__ = "user_addresses"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    address_label: Mapped[str | None] = mapped_column(String)
    recipient_name: Mapped[str] = mapped_column(String, nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String, nullable=False)
    zip_code: Mapped[str | None] = mapped_column(String)
    address_line1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line2: Mapped[str | None] = mapped_column(Text)
    delivery_request: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user = relationship("User")
