"""unacast density cells: size requests before sending them

Revision ID: a7c2d9e41b36
Revises: f6a1b2c3d4e5
Create Date: 2026-09-11 12:00:00.000000+00:00

Requests used to be packed by feature count (always 10), but the vendor's
processing time tracks observation volume. Ten dense Midtown POIs over 30 days
never answered inside the 195 s timeout and were re-sent four times (thread
77e403d3). Sizing a request needs a density estimate for POIs never fetched
before, which their neighbours' paid responses already provide.

One row per ~1 km cell (lat/lng rounded to 2 dp). Aggregate only — no device
ids, no POI identity — so no retention applies.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c2d9e41b36'
down_revision: Union[str, None] = 'f6a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'unacast_density_cells',
        sa.Column('cell', sa.String(length=24), primary_key=True),
        sa.Column('obs_per_m2_day', sa.Float(), nullable=False),
        sa.Column('samples', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('unacast_density_cells')
