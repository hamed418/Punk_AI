"""unacast raw observations: unique (poi_key, maid, observed_at)

Revision ID: d4e9a2b35c01
Revises: c3d8f1a24b90
Create Date: 2026-09-10 21:05:00.000000+00:00

Defence in depth behind `persist_rows`' coverage upsert.

Before that upsert existed, `covered_days` -> `persist_rows` was a read-then-write
race: two sessions extracting the same POI-day both saw it uncovered, both
fetched, and both inserted. The table has only non-unique indexes, so the
duplicates persisted — and a duplicated ping double-counts, inflating visit
counts so `min_visits` fires on devices that never qualified.

**The dedup below must run before the index is created.** Those duplicates may
already exist in a deployed database, and `CREATE UNIQUE INDEX` against them
fails — which is not just a local inconvenience: `cloudbuild.yaml` runs
`python /app/migrate.py` (`upgrade head`) as a build step, so a failing
migration blocks every deploy. Keeping `min(id)` is arbitrary but stable: the
rows are identical in every column the index covers.

`cell_id` is deliberately NOT part of the key. It is deprecated (superseded by
`poi_key`, which is the vendor's own attribution) and is written as `""`, so
including it would add nothing and would break once the column is dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e9a2b35c01'
down_revision: Union[str, None] = 'c3d8f1a24b90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop duplicates first, or the unique index cannot be built.
    op.execute(
        """
        DELETE FROM unacast_raw_observations a
        USING unacast_raw_observations b
        WHERE a.id > b.id
          AND a.poi_key = b.poi_key
          AND a.maid = b.maid
          AND a.observed_at = b.observed_at
        """
    )
    op.create_index(
        'uq_unacast_raw_poi_maid_ts',
        'unacast_raw_observations',
        ['poi_key', 'maid', 'observed_at'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_unacast_raw_poi_maid_ts', table_name='unacast_raw_observations')
