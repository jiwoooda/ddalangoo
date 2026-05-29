"""defer user_preference_feedbacks table

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-29 00:00:00.000000

MVP에서는 user_preference_cache만 유지한다.
명시적 feedback table과 pgvector memory는 Phase 2로 보류한다.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Phase 2까지 no-op으로 둔다."""
    pass


def downgrade() -> None:
    """이미 적용된 DB에 테이블이 남아 있으면 안전하게 제거한다."""
    op.execute("DROP TABLE IF EXISTS user_preference_feedbacks CASCADE")
