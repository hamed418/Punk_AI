"""coupon_redemptions.coupon_id — ON DELETE CASCADE

Revision ID: 7d3b145a901e
Revises: 12ffbbefd784
Create Date: 2026-09-23 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d3b145a901e'
down_revision: Union[str, None] = '12ffbbefd784'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = 'coupon_redemptions_coupon_id_fkey'


def _existing_fk_name() -> str | None:
    for fk in sa.inspect(op.get_bind()).get_foreign_keys('coupon_redemptions'):
        if fk['constrained_columns'] == ['coupon_id']:
            return fk['name']
    return None


def _swap(ondelete: str) -> None:
    existing = _existing_fk_name()
    if existing:
        op.drop_constraint(existing, 'coupon_redemptions', type_='foreignkey')
    op.create_foreign_key(
        FK_NAME,
        'coupon_redemptions',
        'coupons',
        ['coupon_id'],
        ['id'],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _swap('CASCADE')


def downgrade() -> None:
    _swap('RESTRICT')
