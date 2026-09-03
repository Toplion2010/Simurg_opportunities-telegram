"""Add opportunities.digested_at for the daily digest routine

Marks the instant a pending row was selected into a daily digest (auto-
approved or pushed to an admin for review), so a later run the same day
never re-selects it and a candidate is only ever surfaced once. Nullable and
additive — backward compatible with code already deployed.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("digested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("opportunities", "digested_at")
