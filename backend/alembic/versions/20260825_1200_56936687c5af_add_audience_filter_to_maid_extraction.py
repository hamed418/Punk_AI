"""Add audience_filter/filtered_maid_count to maid_extractions

Revision ID: 56936687c5af
Revises: 9957a8b631c7
Create Date: 2026-08-25 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56936687c5af'
down_revision: Union[str, None] = '9957a8b631c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('maid_extractions', sa.Column('audience_filter', sa.JSON(), nullable=True))
    op.add_column('maid_extractions', sa.Column('filtered_maid_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('maid_extractions', 'filtered_maid_count')
    op.drop_column('maid_extractions', 'audience_filter')
