"""add user_preference_feedbacks table

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-29 00:00:00.000000

명시적 사용자 선호/비선호 피드백을 SQL row로 저장한다.
pgvector 기반 장기 메모리는 Phase 2로 미루고, 지금은 원문과 구조화 필드만 저장한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """명시적 사용자 피드백 저장 테이블을 생성한다."""
    op.create_table(
        "user_preference_feedbacks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("recommendation_item_id", sa.BigInteger(), nullable=True),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("product_option_id", sa.BigInteger(), nullable=True),
        sa.Column("feedback_type", sa.String(), nullable=False),
        sa.Column("feedback_target", sa.String(), nullable=True),
        sa.Column("feedback_value", sa.String(), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "is_long_term_memory_candidate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("applied_scope", sa.String(), nullable=True),
        sa.Column(
            "is_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["conversation_messages.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["product_option_id"], ["product_options.id"]),
        sa.ForeignKeyConstraint(["recommendation_item_id"], ["recommendation_items.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_preference_feedbacks_user_id",
        "user_preference_feedbacks",
        ["user_id"],
    )
    op.create_index(
        "ix_user_preference_feedbacks_conversation_id",
        "user_preference_feedbacks",
        ["conversation_id"],
    )
    op.create_index(
        "ix_user_preference_feedbacks_recommendation_item_id",
        "user_preference_feedbacks",
        ["recommendation_item_id"],
    )


def downgrade() -> None:
    """명시적 사용자 피드백 저장 테이블을 제거한다."""
    op.drop_index(
        "ix_user_preference_feedbacks_recommendation_item_id",
        table_name="user_preference_feedbacks",
    )
    op.drop_index(
        "ix_user_preference_feedbacks_conversation_id",
        table_name="user_preference_feedbacks",
    )
    op.drop_index("ix_user_preference_feedbacks_user_id", table_name="user_preference_feedbacks")
    op.drop_table("user_preference_feedbacks")
