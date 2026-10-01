"""Add opportunities.reminder_sent_at

Stamped when src/publisher/reminders.py posts the "N days left to apply"
reminder for a published opportunity, so it is never sent twice. Nullable and
additive -- backward compatible with code already deployed.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("reminder_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("opportunities", "reminder_sent_at")
