"""Add triage fields: relevance, relevance_reason, min_age, source_url

Adds four nullable columns to opportunities so the admin queue can rank by
profile fit, show a one-line reason, gate 18+ content out of the school
channel, and link back to the original post. All nullable and additive —
backward compatible with code already deployed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("relevance", sa.Integer(), nullable=True))
    op.add_column(
        "opportunities", sa.Column("relevance_reason", sa.String(length=120), nullable=True)
    )
    op.add_column("opportunities", sa.Column("min_age", sa.Integer(), nullable=True))
    op.add_column("opportunities", sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("opportunities", "source_url")
    op.drop_column("opportunities", "min_age")
    op.drop_column("opportunities", "relevance_reason")
    op.drop_column("opportunities", "relevance")
