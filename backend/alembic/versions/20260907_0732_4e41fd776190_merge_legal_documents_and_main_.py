"""merge legal documents and main migration branches

Revision ID: 4e41fd776190
Revises: a1c9f4e73b02, 3b329f266374
Create Date: 2026-09-07 07:32:45.189931+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e41fd776190'
down_revision: Union[str, None] = ('a1c9f4e73b02', '3b329f266374')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
