"""Multi-opportunity extraction + AI-written card text fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("card_summary", sa.Text, nullable=True))
    op.add_column("opportunities", sa.Column("card_eligibility", sa.Text, nullable=True))
    op.add_column("opportunities", sa.Column("card_rewards", sa.Text, nullable=True))
    op.add_column("opportunities", sa.Column("extra_notes", sa.Text, nullable=True))
    op.add_column("opportunities", sa.Column("source_excerpt", sa.Text, nullable=True))
    op.add_column(
        "opportunities",
        sa.Column(
            "additional_links",
            sa.Text if op.get_bind().dialect.name == "sqlite" else postgresql.ARRAY(sa.String),
            nullable=False,
            # '{}' is the empty-array literal Postgres requires; "" is only valid
            # for the SQLite Text fallback.
            server_default="" if op.get_bind().dialect.name == "sqlite" else "{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("opportunities", "additional_links")
    op.drop_column("opportunities", "source_excerpt")
    op.drop_column("opportunities", "extra_notes")
    op.drop_column("opportunities", "card_rewards")
    op.drop_column("opportunities", "card_eligibility")
    op.drop_column("opportunities", "card_summary")
