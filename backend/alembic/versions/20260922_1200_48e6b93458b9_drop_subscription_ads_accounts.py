"""drop subscription_ads_accounts

Revision ID: 48e6b93458b9
Revises: 7c95fa3e6847
Create Date: 2026-09-22 12:00:00.000000+00:00

Nothing ever wrote this join table. The check that read it
(AdsAccountSubscriptionService.is_ads_account_authorized) treated "no join row
and no ad_account_id" as authorizing EVERY account, and was replaced by
services/entitlement.ad_account_is_paid, which reads
UserSubscription.ad_account_id only. Dropping the table so that shape cannot
come back.

Refuses to run if the table somehow holds rows: the drop is the one
irreversible step here, and "nothing ever wrote it" is a claim about the code,
not about production.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '48e6b93458b9'
down_revision: Union[str, None] = '7c95fa3e6847'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Offline (--sql) mode has no connection to count on; that mode only prints DDL.
    if not context.is_offline_mode():
        rows = op.get_bind().execute(
            sa.text("SELECT count(*) FROM subscription_ads_accounts")
        ).scalar()
        if rows:
            raise RuntimeError(
                f"subscription_ads_accounts holds {rows} row(s) — refusing to drop. "
                "Inspect them before removing this table."
            )
    op.drop_index(op.f('ix_subscription_ads_accounts_ads_account_id'), table_name='subscription_ads_accounts')
    op.drop_table('subscription_ads_accounts')


def downgrade() -> None:
    op.create_table('subscription_ads_accounts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('subscription_id', sa.UUID(), nullable=False),
    sa.Column('ads_account_id', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['subscription_id'], ['user_subscriptions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subscription_ads_accounts_ads_account_id'), 'subscription_ads_accounts', ['ads_account_id'], unique=False)
