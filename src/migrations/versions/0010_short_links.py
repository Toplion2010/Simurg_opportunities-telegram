"""Add short_links + link_clicks for branded redirect URLs

hackathon-watcher posts link the event title to PUBLIC_BASE_URL/<slug> instead
of the organizer's URL. The Vercel function resolves the slug here, records a
click and 302s to destination_url with utm_* attribution appended.

  short_links   slug -> destination_url, plus a denormalised click counter
  link_clicks   one row per human click, timestamp only (no IP / UA)

New tables only -- nothing existing is altered, so this is backward compatible
with code already deployed. Until it runs, the watcher simply falls back to the
organizer URL (its DB writes fail closed) and the redirect route 302s to the
channel.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "short_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("destination_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="hackathon"),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_clicked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("slug", name="uq_short_links_slug"),
    )
    # The watcher looks a URL up before minting a slug, so a hackathon that is
    # posted twice keeps one slug instead of growing -2, -3 ...
    op.create_index("ix_short_links_destination_url", "short_links", ["destination_url"])

    op.create_table(
        "link_clicks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "link_id",
            sa.Integer(),
            sa.ForeignKey("short_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clicked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_link_clicks_link_id", "link_clicks", ["link_id"])


def downgrade() -> None:
    op.drop_index("ix_link_clicks_link_id", table_name="link_clicks")
    op.drop_table("link_clicks")
    op.drop_index("ix_short_links_destination_url", table_name="short_links")
    op.drop_table("short_links")
