"""unacast device id source: temporary areas/devices audience path

Revision ID: c4f9e2a68b31
Revises: b3e7d1c5a820
Create Date: 2026-09-12 14:00:00.000000+00:00

Our observations entitlement currently emits Unacast's own Pseudonymized
Registration ID, not a real advertising ID, so pings bought from
observations/geo/search cannot be published to Meta as a MADID audience.
/areas/devices returns advertising IDs on this key today. This adds a
`src` marker so device-list rows (one synthetic row per (device, feature),
no position/flags) are provenance-tagged and can be:

  * excluded from ping-density math (observed_daily_rate, the density atlas)
    which assumes one row per real GPS fix
  * skipped by the accuracy/flags gate, which has no evidence to judge
  * bulk-deleted in one statement the day the observations entitlement
    flips to advertiserID mode (see unacast_devices.py's module docstring)

Additive and nullable; NULL means "from observations/geo/search" (every
row written before this migration, and everything after it once the
temporary path is deleted).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4f9e2a68b31'
down_revision: Union[str, None] = 'b3e7d1c5a820'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'unacast_raw_observations',
        sa.Column('src', sa.String(length=8), nullable=True),
    )
    op.add_column(
        'unacast_fetch_coverage',
        sa.Column('src', sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('unacast_fetch_coverage', 'src')
    op.drop_column('unacast_raw_observations', 'src')
