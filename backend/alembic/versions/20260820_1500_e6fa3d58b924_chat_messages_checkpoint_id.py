"""chat_messages.checkpoint_id

The LangGraph checkpoint the thread was sitting on when this message was written.

Undo rewinds to the checkpoint stamped on the PREVIOUS assistant message — the
state before the answer being undone, i.e. paused at the interrupt that answer
replied to. Replaying from there re-fires ``interrupt()`` and the widget comes
back on its own.

Nullable on purpose: rows written before this column existed carry no stamp, and
``ChatService._can_undo`` treats a missing stamp as "not undoable" rather than
guessing at a checkpoint. No backfill is possible — the mapping from an old row
to a checkpoint id was never recorded.

Not indexed: it is only ever read for the two most recent assistant rows of one
conversation, which the existing ``conversation_id`` index already narrows.

Parented on ``c75a998e9f20`` rather than on the newest revision by date. The
chain forks at ``c4d8a1f3e207``: one branch carries the ads_accounts tracking
columns, the other the user_session work, and deployed databases follow the
latter. This column has nothing to do with either, so it sits on the branch that
is actually deployed instead of stranding chat undo behind an unrelated
migration.

Revision ID: e6fa3d58b924
Revises: c75a998e9f20
Create Date: 2026-08-20 15:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6fa3d58b924"
down_revision: Union[str, None] = "c75a998e9f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_messages "
        "ADD COLUMN IF NOT EXISTS checkpoint_id VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS checkpoint_id")
