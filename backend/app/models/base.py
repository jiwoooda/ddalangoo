from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 SQLAlchemy ORM 모델이 상속하는 공통 Base 클래스다."""


class IdMixin:
    """대부분의 비즈니스 테이블에서 사용하는 bigint PK 컬럼이다."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class CreatedAtMixin:
    """생성 시각만 필요한 로그/이력 테이블용 mixin이다."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    """생성/수정 시각을 함께 관리하는 일반 테이블용 mixin이다."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
