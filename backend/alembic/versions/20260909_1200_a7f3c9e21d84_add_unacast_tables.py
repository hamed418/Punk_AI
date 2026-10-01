"""add unacast integration tables

Revision ID: a7f3c9e21d84
Revises: c2b4e891f3a5
Create Date: 2026-09-09 12:00:00.000000+00:00

See docs/maid_unacast_integration_plan.md and
docs/maid_unacast_implementation_tasks.md for why these three tables exist:
  unacast_raw_observations   - durable, cross-campaign raw-ping cache (the
                                budget-protecting store; NOT the same as
                                maid_extractions.observations, which stays
                                per-session and purge-on-publish, untouched)
  unacast_fetch_coverage     - the watermark: which (poi_key, date) pairs are
                                already paid for
  unacast_usage_ledger       - the shared, first-come-first-served monthly
                                observation budget
  unacast_concurrency_leases - the shared, first-come-first-served
                                concurrent-call gate (one lease row per
                                in-flight call)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7f3c9e21d84'
down_revision: Union[str, None] = 'c2b4e891f3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'unacast_raw_observations',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('poi_key', sa.String(length=64), nullable=False),
        sa.Column('maid', sa.String(length=64), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cell_id', sa.String(length=20), nullable=False),
        sa.Column('forensic_flags', sa.BigInteger(), nullable=True),
        sa.Column('hot', sa.Boolean(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_unacast_raw_observations_poi_key', 'unacast_raw_observations', ['poi_key'], unique=False)
    op.create_index('ix_unacast_raw_observations_maid', 'unacast_raw_observations', ['maid'], unique=False)
    op.create_index('idx_unacast_raw_poi_ts', 'unacast_raw_observations', ['poi_key', 'observed_at'], unique=False)

    op.create_table(
        'unacast_fetch_coverage',
        sa.Column('poi_key', sa.String(length=64), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('poi_key', 'date'),
    )

    op.create_table(
        'unacast_usage_ledger',
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('observations_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('provisional_reserved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('calls_made', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('period'),
    )

    op.create_table(
        'unacast_concurrency_leases',
        sa.Column('lease_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('acquired_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('lease_id'),
    )


def downgrade() -> None:
    op.drop_table('unacast_concurrency_leases')
    op.drop_table('unacast_usage_ledger')
    op.drop_table('unacast_fetch_coverage')
    op.drop_index('idx_unacast_raw_poi_ts', table_name='unacast_raw_observations')
    op.drop_index('ix_unacast_raw_observations_maid', table_name='unacast_raw_observations')
    op.drop_index('ix_unacast_raw_observations_poi_key', table_name='unacast_raw_observations')
    op.drop_table('unacast_raw_observations')
