"""unacast coverage: truncated

Revision ID: c3d8f1a24b90
Revises: 160476d1740f
Create Date: 2026-09-10 21:00:00.000000+00:00

`/observations/geo/search` DIRECT returns at most 100,000 observations PER
FEATURE and sets `observationLimitHit` when it truncates. A truncated POI's
pings are a partial, non-random sample, so its frequency counts are FLOORS
rather than measurements — exactly what a `min_visits` predicate must not treat
as fact.

That was recorded only in `unacast_query._TRUNCATED_FEATURES`, an in-process
dict. It survives long enough for the extraction that made the call to disclose
the truncation — but not for a CACHE-ONLY re-run, which is the common case once
the watermark is warm: no API call, no dict entry, and the user is told a
sampled audience is complete.

Nullable rather than NOT NULL DEFAULT false: rows written before this column
existed genuinely do not know whether their fetch truncated, and "unknown" is
not "was not truncated". Backfilling them to false would manufacture a
disclosure we never made.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d8f1a24b90'
down_revision: Union[str, None] = '160476d1740f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'unacast_fetch_coverage',
        sa.Column('truncated', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('unacast_fetch_coverage', 'truncated')
