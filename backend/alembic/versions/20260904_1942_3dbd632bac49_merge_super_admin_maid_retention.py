"""merge super_admin + maid retention

Revision ID: 3dbd632bac49
Revises: c1a2b3d4e5f6, ff06931c4ee3
Create Date: 2026-09-04 19:42:59.612160+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3dbd632bac49'
down_revision: Union[str, None] = ('c1a2b3d4e5f6', 'ff06931c4ee3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
