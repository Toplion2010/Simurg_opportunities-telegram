"""Add target-audience column (school / university / both) for channel routing

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"

    # Only create the ENUM type for PostgreSQL. Exactly 3 values — 'none' is never
    # persisted (it's the pipeline's drop signal, filtered out before a row is built).
    if is_pg:
        op.execute("CREATE TYPE audience AS ENUM ('school','university','both')")

    op.add_column(
        "opportunities",
        sa.Column(
            "audience",
            sa.String(50) if not is_pg else postgresql.ENUM(name="audience", create_type=False),
            nullable=False,
            server_default="both",
        ),
    )


def downgrade() -> None:
    op.drop_column("opportunities", "audience")

    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS audience")
