from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    """서비스 사용자 기본 정보 테이블이다."""

    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String, nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String, index=True, unique=True)
    age_group: Mapped[str | None] = mapped_column(String)
    gender: Mapped[str | None] = mapped_column(String)
    # MVP에서는 nullable. 전화번호만으로 로그인하고, 추후 비밀번호 기능 추가 시 채운다.
    password_hash: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    naver_accounts: Mapped[list["UserNaverAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    platform_sessions: Mapped[list["UserPlatformSession"]] = relationship(  # type: ignore[name-defined]
        "UserPlatformSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserNaverAccount(IdMixin, TimestampMixin, Base):
    """사용자와 네이버 계정/네이버페이 연동 정보를 연결한다."""

    __tablename__ = "user_naver_accounts"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    naver_user_id: Mapped[str | None] = mapped_column(String)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="naver_accounts")
