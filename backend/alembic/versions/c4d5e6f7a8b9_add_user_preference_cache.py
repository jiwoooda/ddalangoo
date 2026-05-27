"""add user_preference_cache table

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-26 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """선호도 계산 결과를 JSONB 캐시로 저장하는 테이블을 만든다."""
    op.create_table(
        "user_preference_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("preference_type", sa.String(), nullable=False),
        sa.Column("keywords_key", sa.String(), nullable=False, server_default=""),
        sa.Column("preference_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "preference_type",
            "keywords_key",
            name="uq_user_preference_cache_key",
        ),
    )
    op.create_index(
        "ix_user_preference_cache_user_id",
        "user_preference_cache",
        ["user_id"],
    )


def downgrade() -> None:
    """선호도 캐시 테이블을 제거한다."""
    op.drop_index("ix_user_preference_cache_user_id", table_name="user_preference_cache")
    op.drop_table("user_preference_cache")
