"""unacast-only cleanup: drop the legacy MAID data

Revision ID: f6a1b2c3d4e5
Revises: e5fab3c46d12
Create Date: 2026-09-11 09:00:00.000000+00:00

The audience path is Unacast-only. This removes what only the legacy paths used,
and the saved data built under the old keys:

  * ``device_observations`` — the bulk-ingested table the Postgres querier read.
    No code reads it any more.
  * every ``maid_extractions`` row — the saved audiences. They were built under a
    ``poi_key`` that mixed in the place name (and so never matched the key the
    executor computed) and under the legacy fallbacks this change removes, so
    none of them re-derive correctly. A chat session that referenced one sees
    "no audience" and re-runs extraction.
  * ``unacast_raw_observations`` + ``unacast_fetch_coverage`` — the ping cache and
    its watermark, keyed by that old ``poi_key``. Truncated TOGETHER: a watermark
    row without its pings would mark a POI-day as paid for and serve an empty
    audience for it forever.
  * ``unacast_raw_observations.cell_id`` — the retired H3 fold column.

``unacast_usage_ledger`` is deliberately kept: calls already spent this month
count against the shared budget whatever the cache holds.

IRREVERSIBLE for data. The downgrade restores the schema only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, None] = 'e5fab3c46d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_observations")
    op.execute("DELETE FROM maid_extractions")
    op.execute("TRUNCATE unacast_raw_observations, unacast_fetch_coverage")
    op.drop_column('unacast_raw_observations', 'cell_id')


def downgrade() -> None:
    op.add_column(
        'unacast_raw_observations',
        sa.Column('cell_id', sa.String(length=20), nullable=True),
    )
    op.create_table(
        'device_observations',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('maid', sa.String(length=64), nullable=False),
        sa.Column('aid_type', sa.String(length=8), nullable=True),
        sa.Column('observed_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('h3_cell', sa.String(length=16), nullable=False),
    )
    op.create_index('idx_device_obs_h3_ts', 'device_observations', ['h3_cell', 'observed_at'])
