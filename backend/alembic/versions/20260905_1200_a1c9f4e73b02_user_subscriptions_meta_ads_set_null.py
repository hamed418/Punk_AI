"""user_subscriptions.meta_ads_id — ON DELETE SET NULL, not CASCADE

A Meta disconnect (a plain user disconnect, or Meta's own deletion callback)
was deleting the user's subscription row — Stripe linkage included — along
with the oauth_tokens row it referenced. The subscription outlives the ad
connection; only the pointer to it should be cleared.

Revision ID: a1c9f4e73b02
Revises: 016398ccf69e
Create Date: 2026-09-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c9f4e73b02'
down_revision: Union[str, None] = '016398ccf69e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = 'fk_user_subscriptions_meta_ads_id'


def _existing_fk_name() -> str | None:
    # user_subscriptions predates this repo's alembic history (nothing in
    # versions/ creates it) and the project sets no naming_convention, so the
    # constraint carries whatever name Postgres happened to assign it —
    # ask the database rather than guess.
    for fk in sa.inspect(op.get_bind()).get_foreign_keys('user_subscriptions'):
        if fk['constrained_columns'] == ['meta_ads_id']:
            return fk['name']
    return None


def _swap(ondelete: str) -> None:
    existing = _existing_fk_name()
    if existing:
        op.drop_constraint(existing, 'user_subscriptions', type_='foreignkey')
    op.create_foreign_key(
        FK_NAME, 'user_subscriptions', 'oauth_tokens',
        ['meta_ads_id'], ['id'], ondelete=ondelete,
    )


def upgrade() -> None:
    _swap('SET NULL')


def downgrade() -> None:
    _swap('CASCADE')
