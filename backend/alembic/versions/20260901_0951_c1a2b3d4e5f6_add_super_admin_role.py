"""Add super_admin to userrole enum

Revision ID: c1a2b3d4e5f6
Revises: a93a65af1cb4
Create Date: 2026-09-01 09:51:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'a93a65af1cb4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'super_admin' to the userrole PostgreSQL enum type
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'super_admin'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    # This downgrade is intentionally a no-op — removing a role value
    # while data may reference it would be destructive.
    pass
