"""add gender to users

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-05-28 00:00:00.000000

users 테이블에 성별 컬럼을 추가한다. nullable, 선택 입력.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("gender", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "gender")
