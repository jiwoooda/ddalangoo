"""drop unused user_preferences table

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """런타임 코드에서 사용하지 않는 legacy user_preferences 테이블을 제거한다."""
    op.execute("DROP TABLE IF EXISTS user_preferences CASCADE")


def downgrade() -> None:
    """롤백 시 기존 legacy user_preferences 테이블 형태를 복구한다."""
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.String(), nullable=True),
        sa.Column("preferred_brands", sa.JSON(), nullable=True),
        sa.Column("price_range", sa.JSON(), nullable=True),
        sa.Column("repurchase_patterns", sa.JSON(), nullable=True),
        sa.Column("preferred_platform", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
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
    )
    op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_user_preferences_general "
        "ON user_preferences (user_id) "
        "WHERE keyword IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_user_preferences_keyword "
        "ON user_preferences (user_id, keyword) "
        "WHERE keyword IS NOT NULL"
    )
