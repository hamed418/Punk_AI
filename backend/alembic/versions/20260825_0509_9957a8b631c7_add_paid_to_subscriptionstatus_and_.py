"""Add paid to SubscriptionStatus and SubscriptionPaymentStatus

Revision ID: 9957a8b631c7
Revises: 1142bbdf7982
Create Date: 2026-08-25 05:09:04.087556+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9957a8b631c7'
down_revision: Union[str, None] = '1142bbdf7982'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'paid'")
    op.execute("ALTER TYPE subscriptionpaymentstatus ADD VALUE IF NOT EXISTS 'paid'")

def downgrade() -> None:
    pass
