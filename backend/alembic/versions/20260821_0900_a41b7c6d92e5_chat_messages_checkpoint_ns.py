"""chat_messages.checkpoint_ns

The other half of the rewind address. ``checkpoint_id`` alone cannot identify a
step: ``campaign_builder`` is a compiled subgraph, and while it is the pending
parent task every internal ``interrupt()`` happens inside ONE parent superstep,
so the parent checkpoint never advances. Three consecutive builder steps were
observed carrying one identical ``checkpoint_id``, which made every rewind fork
to the same point — the subgraph's first interrupt — regardless of which answer
the user picked.

The per-step state lives under ``checkpoint_ns = "campaign_builder:<task_id>"``,
so the namespace has to be stored alongside the id and forked together.

Nullable, and deliberately not backfilled: for existing rows the stored
``checkpoint_id`` is the ambiguous parent stamp and the mapping to the real
subgraph checkpoint was never recorded. ``checkpoint_ns IS NULL`` therefore means
"not rewindable" rather than "rewind to the parent" — trusting the old stamp
would silently rewind to the wrong step. Note that ``''`` is a legitimate value
(a pause in the parent graph), so callers must test ``is not None``.

Revision ID: a41b7c6d92e5
Revises: 7e0de74e4723
Create Date: 2026-08-21 09:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a41b7c6d92e5"
down_revision: Union[str, None] = "7e0de74e4723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_messages "
        "ADD COLUMN IF NOT EXISTS checkpoint_ns VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS checkpoint_ns")
