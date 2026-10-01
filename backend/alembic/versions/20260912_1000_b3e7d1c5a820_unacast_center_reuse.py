"""unacast center reuse: serve a smaller ring from a larger purchase

Revision ID: b3e7d1c5a820
Revises: a7c2d9e41b36
Create Date: 2026-09-12 10:00:00.000000+00:00

`poi_key` hashes the ring radius, and must: a 100 m purchase served as a 500 m
audience was a live bug. But it also meant a later request for a SMALLER ring at
the same centre re-bought pings it already had. Pings are now stored under the
centre alone and read back by distance, and coverage records what each day was
bought at:

  * center_key on both tables — the rounded coordinates, no radius.
  * radius_m on coverage — a day covered at R serves any ring r <= R.
  * window_days on coverage — a truncated day bought inside a multi-day feature
    can be repaired with a narrower one; a truncated one-day feature cannot.

All additive and nullable. Rows written before this carry no centre and are not
reused across radii; their days are re-bought once and the old rows age out
under the 90-day retention sweep.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3e7d1c5a820'
down_revision: Union[str, None] = 'a7c2d9e41b36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'unacast_raw_observations',
        sa.Column('center_key', sa.String(length=32), nullable=True),
    )
    op.create_index(
        'idx_unacast_raw_center_ts', 'unacast_raw_observations',
        ['center_key', 'observed_at'],
    )
    op.create_index(
        'uq_unacast_raw_center_maid_ts', 'unacast_raw_observations',
        ['center_key', 'maid', 'observed_at'],
        unique=True, postgresql_where=sa.text('center_key IS NOT NULL'),
    )
    op.add_column(
        'unacast_fetch_coverage',
        sa.Column('center_key', sa.String(length=32), nullable=True),
    )
    op.add_column('unacast_fetch_coverage', sa.Column('radius_m', sa.Integer(), nullable=True))
    op.add_column(
        'unacast_fetch_coverage', sa.Column('window_days', sa.Integer(), nullable=True),
    )
    op.create_index(
        'idx_unacast_coverage_center_date', 'unacast_fetch_coverage', ['center_key', 'date'],
    )


def downgrade() -> None:
    op.drop_index('idx_unacast_coverage_center_date', table_name='unacast_fetch_coverage')
    op.drop_column('unacast_fetch_coverage', 'window_days')
    op.drop_column('unacast_fetch_coverage', 'radius_m')
    op.drop_column('unacast_fetch_coverage', 'center_key')
    op.drop_index('uq_unacast_raw_center_maid_ts', table_name='unacast_raw_observations')
    op.drop_index('idx_unacast_raw_center_ts', table_name='unacast_raw_observations')
    op.drop_column('unacast_raw_observations', 'center_key')
