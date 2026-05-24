"""add product delivery fields

Revision ID: 91c7f1d7a5b2
Revises: 03ebc4ef2983
Create Date: 2026-05-25 03:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "91c7f1d7a5b2"
down_revision: Union[str, Sequence[str], None] = "03ebc4ef2983"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """products에 현재 배송 분류와 표시용 배송 정보를 추가한다."""
    op.add_column("products", sa.Column("delivery_type", sa.String(), nullable=True))
    op.add_column("products", sa.Column("current_delivery_info", sa.String(), nullable=True))


def downgrade() -> None:
    """products 배송 정보 컬럼을 제거한다."""
    op.drop_column("products", "current_delivery_info")
    op.drop_column("products", "delivery_type")
