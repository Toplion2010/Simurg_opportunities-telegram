"""Allow non-Telegram sources: web-scraped opportunity catalogs

Simurg's collector was Telegram-only *by schema* — source_channels.telegram_id
and raw_messages.telegram_msg_id were both BigInteger NOT NULL, so there was
nowhere to put a scraped item. This makes both nullable and adds the columns a
second collector kind needs:

  source_channels.kind        'telegram' | 'web'
  source_channels.identifier  registry key for a web scraper
  source_channels.cursor      opaque per-source resume token
  raw_messages.external_id    stable per-source item id (a slug)

Deliberately NOT a rename to a `sources` table: that would touch the collector,
the repositories, the bot and three workflows for no functional gain.

Every existing row takes kind='telegram' from the server default, so the
Telegram path is untouched and this is backward compatible with code already
deployed — old code simply never reads the new columns.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- source_channels ------------------------------------------------
    # telegram_id keeps its UNIQUE constraint; Postgres permits many NULLs in a
    # unique column, so any number of web rows can coexist.
    op.alter_column(
        "source_channels",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "source_channels",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="telegram",
        ),
    )
    op.add_column(
        "source_channels", sa.Column("identifier", sa.String(length=200), nullable=True)
    )
    op.add_column("source_channels", sa.Column("cursor", sa.Text(), nullable=True))
    # Partial: only web rows carry an identifier, and NULL identifiers must not
    # collide with each other on the ~42 existing Telegram rows.
    op.create_index(
        "ix_source_channels_kind_identifier",
        "source_channels",
        ["kind", "identifier"],
        unique=True,
        postgresql_where=sa.text("identifier IS NOT NULL"),
    )

    # --- raw_messages ---------------------------------------------------
    op.alter_column(
        "raw_messages",
        "telegram_msg_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "raw_messages", sa.Column("external_id", sa.String(length=200), nullable=True)
    )
    op.create_index(
        "ix_raw_messages_source_external",
        "raw_messages",
        ["source_channel_id", "external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_messages_source_external", table_name="raw_messages")
    op.drop_column("raw_messages", "external_id")
    # Rows from web sources have a NULL telegram_msg_id and cannot satisfy the
    # restored NOT NULL, so they must go before it is re-applied. They are
    # reproducible by re-running the collector.
    op.execute(
        "DELETE FROM raw_messages WHERE source_channel_id IN "
        "(SELECT id FROM source_channels WHERE kind = 'web')"
    )
    op.execute("DELETE FROM raw_messages WHERE telegram_msg_id IS NULL")
    op.alter_column(
        "raw_messages",
        "telegram_msg_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

    op.drop_index("ix_source_channels_kind_identifier", table_name="source_channels")
    op.execute("DELETE FROM source_channels WHERE kind = 'web'")
    op.drop_column("source_channels", "cursor")
    op.drop_column("source_channels", "identifier")
    op.drop_column("source_channels", "kind")
    op.alter_column(
        "source_channels",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
