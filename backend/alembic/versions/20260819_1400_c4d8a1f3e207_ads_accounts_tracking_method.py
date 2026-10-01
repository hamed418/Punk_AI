"""ads_accounts.tracking_method

Which way this account reports conversions back to Meta. Until now the answer was
collected on the intake form, shown once on the publish preview, and thrown away —
nothing persisted it, so the tracking card could not tell whether to hand out an
install snippet, a server ingest key, or neither.

Idempotent for the same reason as ``a3f1c07b95de`` and ``b7c2e6d41a8f``: the
chain's root (``832ec00ed47c``) is a reversed autogenerate that drops the tracking
columns, so every migration after it has to survive being applied to a database
that may or may not already carry them.

Revision ID: c4d8a1f3e207
Revises: b7c2e6d41a8f
Create Date: 2026-08-19 14:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8a1f3e207"
down_revision: Union[str, None] = "b7c2e6d41a8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ads_accounts "
        "ADD COLUMN IF NOT EXISTS tracking_method VARCHAR(32)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ads_accounts DROP COLUMN IF EXISTS tracking_method")
