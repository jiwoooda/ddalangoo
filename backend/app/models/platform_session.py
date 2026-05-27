from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class UserPlatformSession(IdMixin, TimestampMixin, Base):
    """사용자별 외부 플랫폼(컬리 등) 로그인 세션 정보를 저장한다.

    MVP: session_file_path 컬럼에 파일 경로만 저장.
    향후 encrypted_session_json 으로 DB 내 암호화 저장 전환 예정.
    """

    __tablename__ = "user_platform_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "platform",
            "account_label",
            "session_type",
            name="uq_user_platform_session",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String, nullable=False)
    account_label: Mapped[str] = mapped_column(
        String, nullable=False, default="default", server_default="default"
    )
    # 플랫폼 자체 사용자 ID (예: 컬리 회원번호)
    external_account_id: Mapped[str | None] = mapped_column(String)
    # 세션 종류. MVP: "playwright_storage_state"
    session_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="playwright_storage_state",
        server_default="playwright_storage_state",
    )
    # 향후 DB 저장 시 암호화된 JSON (nullable → 사용 전까지 비움)
    encrypted_session_json: Mapped[str | None] = mapped_column(Text)
    # MVP: 파일 경로 (예: "sessions/kurly_session_42.json")
    session_file_path: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User", back_populates="platform_sessions")  # type: ignore[name-defined]
