"""Add opportunities story and published-message-reference fields

Lets an admin mark an already-published "cool" opportunity (an international
program with a tight deadline, a standout hackathon, ...) to go out as a
Telegram Story on all three Simurg channels, reposting the real photo of its
live channel message rather than a freshly re-rendered one.

story_requested_at is stamped when the admin taps the queue/search "📸 Story"
button; story_posted_at is stamped once publisher.story.publish_stories
actually sends it, so a later run never reposts the same story.
published_chat_id/published_message_id are stamped by sender.py at publish
time, from the first channel a post actually reached -- story.py needs them
to fetch that live message's real photo later. All four nullable and
additive -- backward compatible with code already deployed.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("story_requested_at", sa.DateTime(), nullable=True))
    op.add_column("opportunities", sa.Column("story_posted_at", sa.DateTime(), nullable=True))
    op.add_column("opportunities", sa.Column("published_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("opportunities", sa.Column("published_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("opportunities", "published_message_id")
    op.drop_column("opportunities", "published_chat_id")
    op.drop_column("opportunities", "story_posted_at")
    op.drop_column("opportunities", "story_requested_at")
