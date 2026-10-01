"""unacast ledger: requests_made

Revision ID: 160476d1740f
Revises: 60366d7d2ae0
Create Date: 2026-09-10 13:42:00.000000+00:00

The ledger counted one "call" per BATCH, but `UnacastClient` retries a 429 or a
5xx internally (its own lease-aware budget, up to `_MAX_ATTEMPTS`). So a single
`reserve_call` could cover several real HTTP requests.

That conflates two different vendor limits:

  * the MONTHLY quota counts API calls  -> `calls_made`
  * a DAILY request limit per API key, 429, resets 00:00 UTC -> `requests_made`

Counting only batches made the ledger read low against the daily limit, so the
system believed it had headroom it did not. `requests_made` is >= `calls_made`
by construction; the transport reports the true count via
`unacast_client.REQUESTS_MADE`, which is derived from the `contacted` list it
already maintained ("a response of any status proves the request reached the
vendor and was therefore metered").

Backfilled to `calls_made` rather than 0: every historical call made at least one
request, so that is the correct floor and is closer to the truth than zero.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '160476d1740f'
down_revision: Union[str, None] = '60366d7d2ae0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'unacast_usage_ledger',
        sa.Column('requests_made', sa.Integer(), nullable=False, server_default='0'),
    )
    op.execute(
        "UPDATE unacast_usage_ledger SET requests_made = calls_made "
        "WHERE requests_made = 0 AND calls_made > 0"
    )


def downgrade() -> None:
    op.drop_column('unacast_usage_ledger', 'requests_made')
