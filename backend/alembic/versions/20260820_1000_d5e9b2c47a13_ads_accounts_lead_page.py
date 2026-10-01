"""ads_accounts.tracking_lead_page_id

The Page whose leadgen webhook this ad account is subscribed to, so an inbound
lead can be routed back to the account that bought the ad. ``oauth_tokens.page_id``
cannot do it: it is whichever Page Meta happened to list first at connect time,
not the Page the campaign published under, and one login can reach several.

Indexed because the lookup is per webhook delivery and scoped by nothing else —
Meta sends the Page id and nothing that identifies us.

Idempotent for the same reason as ``a3f1c07b95de``, ``b7c2e6d41a8f`` and
``c4d8a1f3e207``: the chain's root (``832ec00ed47c``) is a reversed autogenerate
that drops the tracking columns, so every migration after it has to survive being
applied to a database that may or may not already carry them.

Revision ID: d5e9b2c47a13
Revises: c4d8a1f3e207
Create Date: 2026-08-20 10:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e9b2c47a13"
down_revision: Union[str, None] = "c4d8a1f3e207"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ads_accounts "
        "ADD COLUMN IF NOT EXISTS tracking_lead_page_id VARCHAR(100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ads_accounts_tracking_lead_page_id "
        "ON ads_accounts (tracking_lead_page_id) "
        "WHERE tracking_lead_page_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ads_accounts_tracking_lead_page_id")
    op.execute(
        "ALTER TABLE ads_accounts DROP COLUMN IF EXISTS tracking_lead_page_id"
    )
