"""unacast_raw_observations.cell_id nullable (H3 visit fold retired)

Revision ID: b8e1c4d72f90
Revises: a7f3c9e21d84
Create Date: 2026-09-10 06:00:00.000000+00:00

`cell_id` held a self-computed H3 res-10 cell used as the visit fold key, on the
assumption that "which spot is this ping at" had to be inferred from
coordinates. It does not: the observations/geo/search response nests every
observation under the feature it matched, and that feature's id IS the POI key
we sent — so `poi_key` already answers it exactly.

Measured on 287,000 real pings (docs/maid_signal_quality_baseline.md §3), the H3
fold split one real visit across hexagon boundaries for 26.1% of device-POI
pairs and inflated visit counts by 14.5%.

The column is made nullable rather than dropped so the existing rows stay
readable; it is no longer written. Drop it once those rows age out of retention.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8e1c4d72f90'
down_revision: Union[str, None] = 'a7f3c9e21d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'unacast_raw_observations', 'cell_id',
        existing_type=sa.String(length=20),
        nullable=True,
    )


def downgrade() -> None:
    # Rows written after the upgrade have no cell_id, so restoring NOT NULL
    # needs a value. Empty string rather than a recomputed H3 cell: the fold no
    # longer uses this column, and re-deriving it would reintroduce the h3
    # dependency purely to satisfy a constraint nothing reads.
    op.execute("UPDATE unacast_raw_observations SET cell_id = '' WHERE cell_id IS NULL")
    op.alter_column(
        'unacast_raw_observations', 'cell_id',
        existing_type=sa.String(length=20),
        nullable=False,
    )
