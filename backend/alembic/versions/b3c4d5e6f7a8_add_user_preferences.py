"""add user_preferences table

Revision ID: b3c4d5e6f7a8
Revises: 91c7f1d7a5b2
Create Date: 2026-05-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "91c7f1d7a5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """유저 선호도 캐시 테이블을 생성한다."""
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

    # 일반 선호도: 유저당 1건 (keyword IS NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_user_preferences_general "
        "ON user_preferences (user_id) "
        "WHERE keyword IS NULL"
    )

    # 키워드별 선호도: 유저+키워드당 1건 (keyword IS NOT NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_user_preferences_keyword "
        "ON user_preferences (user_id, keyword) "
        "WHERE keyword IS NOT NULL"
    )


def downgrade() -> None:
    """user_preferences 테이블을 삭제한다."""
    op.drop_index("uq_user_preferences_keyword", table_name="user_preferences")
    op.drop_index("uq_user_preferences_general", table_name="user_preferences")
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")
