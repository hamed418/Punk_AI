"""oauth_tokens.token_type — 'user' vs 'system_user' (BISU)

Revision ID: 016398ccf69e
Revises: 3dbd632bac49
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '016398ccf69e'
down_revision: Union[str, None] = '3dbd632bac49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'oauth_tokens',
        sa.Column('token_type', sa.String(length=20), nullable=False, server_default='user'),
    )


def downgrade() -> None:
    op.drop_column('oauth_tokens', 'token_type')
