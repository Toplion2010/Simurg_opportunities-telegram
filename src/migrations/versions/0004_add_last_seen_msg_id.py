"""Track the last Telegram message id fetched per source channel

Lets a scheduled run pull only messages posted since the previous run, so
collection no longer requires a process listening for live events 24/7.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_channels",
        sa.Column("last_seen_msg_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_channels", "last_seen_msg_id")
