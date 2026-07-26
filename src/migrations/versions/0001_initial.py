"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only create ENUMs for PostgreSQL
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""
            CREATE TYPE category AS ENUM (
                'Internship','Scholarship','Fellowship','Research','Competition',
                'Olympiad','Hackathon','Startup','Accelerator','Incubator',
                'Grant','Conference','SummerProgram','Exchange','Volunteer','Job'
            )
        """)
        op.execute("""
            CREATE TYPE opportunitystatus AS ENUM (
                'pending','approved','rejected','published'
            )
        """)

    op.create_table(
        "source_channels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, unique=True, nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("username", sa.String(255)),
        sa.Column("category_hint", sa.Text, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "raw_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "source_channel_id",
            sa.Integer,
            sa.ForeignKey("source_channels.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("telegram_msg_id", sa.BigInteger, nullable=False),
        sa.Column("text", sa.Text),
        sa.Column(
            "received_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("processed", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "raw_message_id",
            sa.Integer,
            sa.ForeignKey("raw_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(500)),
        sa.Column("category", sa.String(100) if op.get_bind().dialect.name == 'sqlite' else postgresql.ENUM(name="category", create_type=False), nullable=True),
        sa.Column("deadline", sa.String(200)),
        sa.Column("eligibility", sa.Text),
        sa.Column("location", sa.String(300)),
        sa.Column("cost", sa.String(300)),
        sa.Column("organizer", sa.String(300)),
        sa.Column("duration", sa.String(200)),
        sa.Column("rewards", sa.Text),
        sa.Column("apply_link", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("rewritten_text", sa.Text),
        sa.Column("media_path", sa.Text),
        sa.Column("similarity_hash", sa.String(64)),
        sa.Column(
            "status",
            sa.String(50) if op.get_bind().dialect.name == 'sqlite' else postgresql.ENUM(name="opportunitystatus", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "hooks",
            sa.Text if op.get_bind().dialect.name == 'sqlite' else postgresql.ARRAY(sa.String),
            nullable=False,
            # Postgres needs the empty-array literal '{}' here; "" is only valid
            # for the SQLite Text fallback and errors as a malformed array literal.
            server_default="" if op.get_bind().dialect.name == 'sqlite' else "{}",
        ),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
    )

    op.create_table(
        "opportunity_tags",
        sa.Column(
            "opportunity_id",
            sa.Integer,
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer,
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_index("ix_opportunities_status", "opportunities", ["status"])
    op.create_index("ix_opportunities_similarity_hash", "opportunities", ["similarity_hash"])
    op.create_index("ix_opportunities_scheduled_at", "opportunities", ["scheduled_at"])


def downgrade() -> None:
    op.drop_table("opportunity_tags")
    op.drop_table("tags")
    op.drop_index("ix_opportunities_scheduled_at", "opportunities")
    op.drop_index("ix_opportunities_similarity_hash", "opportunities")
    op.drop_index("ix_opportunities_status", "opportunities")
    op.drop_table("opportunities")
    op.drop_table("raw_messages")
    op.drop_table("source_channels")
    
    # Only drop types for PostgreSQL
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("DROP TYPE IF EXISTS opportunitystatus")
        op.execute("DROP TYPE IF EXISTS category")
