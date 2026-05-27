"""add user platform sessions

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-28 00:00:00.000000

사용자별 플랫폼(컬리 등) 로그인 세션을 저장하는 테이블을 추가한다.
- MVP: session_file_path 기반 (파일 경로만 저장)
- 향후: encrypted_session_json 으로 DB 내 암호화 저장 전환 예정
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_platform_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column(
            "account_label",
            sa.String(),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("external_account_id", sa.String(), nullable=True),
        sa.Column(
            "session_type",
            sa.String(),
            nullable=False,
            server_default=sa.text("'playwright_storage_state'"),
        ),
        sa.Column("encrypted_session_json", sa.Text(), nullable=True),
        sa.Column("session_file_path", sa.String(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id",
            "platform",
            "account_label",
            "session_type",
            name="uq_user_platform_session",
        ),
    )
    op.create_index(
        "ix_user_platform_sessions_user_id",
        "user_platform_sessions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_platform_sessions_user_id", table_name="user_platform_sessions")
    op.drop_table("user_platform_sessions")
