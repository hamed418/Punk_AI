"""unacast call log: per-user / per-thread attribution for vendor spend

Revision ID: d5a1b3c7e920
Revises: c4f9e2a68b31
Create Date: 2026-09-14 09:00:00.000000+00:00

`unacast_usage_ledger` counts the month's calls platform-wide — it is the budget
guard `reserve_call` contends on, one locked row per period, and it has no idea
WHO spent the quota. This table is the other half: one row per call that
actually reached the vendor, carrying the user and the chat thread behind it.

Written inside the same transaction as the ledger increment
(`unacast_query.reconcile_call`), so SUM(calls) per period and
`unacast_usage_ledger.calls_made` can never disagree — which is what lets a
per-user or per-thread report be reconciled against the month's real total.

`user_id`/`thread_id` are NULL for a call with no chat turn behind it (a script,
the autopilot). Those rows are the reconciling remainder, not rows to drop.

Additive: new table only, nothing existing is altered.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd5a1b3c7e920'
down_revision: Union[str, None] = 'c4f9e2a68b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'unacast_call_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=True,
        ),
        sa.Column('period', sa.String(length=7), nullable=False),
        # SET NULL, not CASCADE: deleting a user must not erase what was already
        # spent on their behalf, or the month stops reconciling.
        sa.Column(
            'user_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('thread_id', sa.String(length=255), nullable=True),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('requests', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('observations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('src', sa.String(length=32), nullable=True),
    )
    op.create_index('ix_unacast_call_log_created_at', 'unacast_call_log', ['created_at'])
    op.create_index('ix_unacast_call_log_period', 'unacast_call_log', ['period'])
    op.create_index('ix_unacast_call_log_user_id', 'unacast_call_log', ['user_id'])
    op.create_index('ix_unacast_call_log_thread_id', 'unacast_call_log', ['thread_id'])


def downgrade() -> None:
    op.drop_index('ix_unacast_call_log_thread_id', table_name='unacast_call_log')
    op.drop_index('ix_unacast_call_log_user_id', table_name='unacast_call_log')
    op.drop_index('ix_unacast_call_log_period', table_name='unacast_call_log')
    op.drop_index('ix_unacast_call_log_created_at', table_name='unacast_call_log')
    op.drop_table('unacast_call_log')
