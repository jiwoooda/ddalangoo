"""add product search executions

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_search_executions",
        sa.Column("search_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("preferred_platform", sa.String(), nullable=True),
        sa.Column("platform_queue", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_platform", sa.String(), nullable=True),
        sa.Column("current_platform_index", sa.Integer(), nullable=False),
        sa.Column("products_by_platform", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("merged_products", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("search_id"),
    )
    op.create_index(
        op.f("ix_product_search_executions_conversation_id"),
        "product_search_executions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_search_executions_status"),
        "product_search_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_search_executions_user_id"),
        "product_search_executions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_product_search_executions_user_id"), table_name="product_search_executions")
    op.drop_index(op.f("ix_product_search_executions_status"), table_name="product_search_executions")
    op.drop_index(op.f("ix_product_search_executions_conversation_id"), table_name="product_search_executions")
    op.drop_table("product_search_executions")
