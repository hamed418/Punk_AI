"""Add audit_logs table

The AuditLog model (app/modules/auditLogs/models.py) predates this migration
but was never created in any prior revision — nothing wrote to it, so the
missing table went unnoticed. First real writer is the go-live consent /
Custom Audience source-disclosure acknowledgement recorded on publish.

Revision ID: ff06931c4ee3
Revises: 685bd7d39142
Create Date: 2026-09-03 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ff06931c4ee3'
down_revision: Union[str, None] = '685bd7d39142'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: at least one dev DB already has this table (and real rows in
    # it) from the AuditLogRepository writer running before this migration
    # existed — a plain create_table there raises DuplicateTableError and
    # aborts the whole (transactional-DDL) upgrade, taking the unrelated
    # maid-retention migrations in this same run down with it. A prod DB never
    # has the table yet, so this still just creates it normally there.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'audit_logs' not in inspector.get_table_names():
        op.create_table(
            'audit_logs',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', sa.String(), nullable=True),
            sa.Column('action', sa.String(length=100), nullable=False),
            sa.Column('resource_type', sa.String(length=100), nullable=True),
            sa.Column('resource_id', sa.String(length=100), nullable=True),
            sa.Column('old_data', sa.JSON(), nullable=True),
            sa.Column('new_data', sa.JSON(), nullable=True),
            sa.Column('ip_address', sa.String(length=50), nullable=True),
            sa.Column('user_agent', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('audit_logs')} if 'audit_logs' in inspector.get_table_names() else set()
    if 'ix_audit_logs_user_id' not in existing_indexes:
        op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    if 'ix_audit_logs_action' not in existing_indexes:
        op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user_id', table_name='audit_logs')
    op.drop_table('audit_logs')
