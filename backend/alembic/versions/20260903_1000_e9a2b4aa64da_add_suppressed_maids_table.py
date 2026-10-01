"""Add suppressed_maids table

Revision ID: e9a2b4aa64da
Revises: a93a65af1cb4
Create Date: 2026-09-03 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9a2b4aa64da'
down_revision: Union[str, None] = 'a93a65af1cb4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suppressed_maids',
        sa.Column('maid', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('maid'),
    )


def downgrade() -> None:
    op.drop_table('suppressed_maids')
