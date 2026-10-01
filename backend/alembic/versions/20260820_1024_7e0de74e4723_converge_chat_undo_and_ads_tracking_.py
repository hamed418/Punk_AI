"""converge chat undo and ads tracking branches

No schema change — this exists only to collapse two heads back into one.

The chain forked at ``c4d8a1f3e207``: one branch carried the ads_accounts
tracking work (ending at ``d5e9b2c47a13``, ``tracking_lead_page_id``), the other
the user_session work (``c75a998e9f20``) that deployed databases actually
followed. With two heads ``alembic upgrade head`` fails outright, and
``upgrade heads`` quietly applies both branches — so whichever branch you were
not thinking about gets dragged along as a side effect.

That fork left ``ads_accounts.tracking_lead_page_id`` unapplied while the ORM
model declared it, which breaks every ``SELECT`` against ``AdsAccount`` (the
column list is generated from the model). Merging applies it and makes
``upgrade head`` mean something again.

Revision ID: 7e0de74e4723
Revises: e6fa3d58b924, d5e9b2c47a13
Create Date: 2026-08-20 10:24:24.634858+00:00
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "7e0de74e4723"
down_revision: Union[str, Sequence[str], None] = ("e6fa3d58b924", "d5e9b2c47a13")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge point only — both parents carry their own DDL."""


def downgrade() -> None:
    """Merge point only — splitting the heads again needs no DDL."""
