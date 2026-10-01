"""Add updated_at/purged_at to maid_extractions (MAID retention)

Revision ID: 685bd7d39142
Revises: e9a2b4aa64da
Create Date: 2026-09-03 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '685bd7d39142'
down_revision: Union[str, None] = 'e9a2b4aa64da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'maid_extractions',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    )
    op.add_column(
        'maid_extractions',
        sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maid_extractions', 'purged_at')
    op.drop_column('maid_extractions', 'updated_at')
