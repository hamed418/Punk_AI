"""usage_events: per-thread / per-user tokens and API calls, queryable in SQL

Revision ID: e6b2c4d8f031
Revises: d5a1b3c7e920
Create Date: 2026-09-14 11:00:00.000000+00:00

Per-thread token totals lived only in the LangGraph checkpoint
(`AgentState.total_tokens` / `token_cost_usd` / `google_api_calls`) and
per-user totals only in `token_transactions.tx_metadata` — the first is not
SQL, and the second is only written when the user had balance, so a 402
recorded nothing against real Gemini spend. Neither is written at all when a
turn ends at a subgraph interrupt, which is how a MAID extraction almost
always ends.

One row per (turn, vendor-surface), written unconditionally and never
raising. `quantity` is TOKENS when kind = 'llm_tokens' and REQUESTS
otherwise — never SUM across kinds, filter by kind first.

Unacast is deliberately absent: `unacast_call_log` already records it
transactionally with the budget ledger (`unacast_query.reconcile_call`).
Admin rollups UNION the two tables at read time instead of duplicating the
write.

No `created_at` index: `period` ('YYYY-MM') serves every time filter this
table is queried by, and this is the highest-insert table in the schema.

Additive: new table only, nothing existing is altered.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e6b2c4d8f031'
down_revision: Union[str, None] = 'd5a1b3c7e920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usage_events',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=True,
        ),
        sa.Column('period', sa.String(length=7), nullable=False),
        # SET NULL, not CASCADE: deleting a user must not erase what was spent.
        sa.Column(
            'user_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('thread_id', sa.String(length=255), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('api', sa.String(length=64), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index('ix_usage_events_period', 'usage_events', ['period'])
    op.create_index('ix_usage_events_user_id', 'usage_events', ['user_id'])
    op.create_index('ix_usage_events_thread_id', 'usage_events', ['thread_id'])


def downgrade() -> None:
    op.drop_index('ix_usage_events_thread_id', table_name='usage_events')
    op.drop_index('ix_usage_events_user_id', table_name='usage_events')
    op.drop_index('ix_usage_events_period', table_name='usage_events')
    op.drop_table('usage_events')
