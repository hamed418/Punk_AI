"""merge redeem codes and unacast cell_id

Revision ID: 60366d7d2ae0
Revises: 22eb57038ee5, b8e1c4d72f90
Create Date: 2026-09-10 13:19:45.081914+00:00

Two feature branches both took a7f3c9e21d84 (the unacast tables) as their parent:

    a7f3c9e21d84
      |- 22eb57038ee5   redeem codes / redemptions
      |- b8e1c4d72f90   unacast_raw_observations.cell_id -> nullable

That left the history with TWO heads, which alembic refuses to `upgrade head`.
It is not only a local inconvenience: cloudbuild.yaml runs `python /app/migrate.py`
(`command.upgrade(cfg, "head")`) as a build step, so **every deploy fails** until
the heads are reconciled.

This revision does nothing but join them. Both branches touch unrelated tables,
so there is no ordering constraint between them and nothing to reconcile beyond
the graph itself.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60366d7d2ae0'
down_revision: Union[str, None] = ('22eb57038ee5', 'b8e1c4d72f90')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
