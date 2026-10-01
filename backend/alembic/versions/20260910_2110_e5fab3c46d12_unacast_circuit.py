"""unacast circuit breaker: shared state

Revision ID: e5fab3c46d12
Revises: d4e9a2b35c01
Create Date: 2026-09-10 21:10:00.000000+00:00

The breaker exists because a call is committed to the ledger before the request
returns — correct, since reaching the vendor consumes quota — so during an
outage every extraction reserves, fires, fails and pays, draining a shared
first-come-first-served monthly budget while returning nothing.

It lived in module globals (`_BREAKER_FAILURES` / `_BREAKER_OPENED_AT`), which
stops only the acute single-worker case. Cloud Run runs this service at
`maxScale=5`: an open breaker in one worker did nothing about the other four,
which kept spending. Breaker state has to be somewhere every worker can see it.

One row, `id = 'unacast'`, seeded here so the query path never has to branch on
"does the row exist yet". `opened_at IS NULL` means closed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5fab3c46d12'
down_revision: Union[str, None] = 'd4e9a2b35c01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'unacast_circuit',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "INSERT INTO unacast_circuit (id, consecutive_failures) VALUES ('unacast', 0)"
    )


def downgrade() -> None:
    op.drop_table('unacast_circuit')
