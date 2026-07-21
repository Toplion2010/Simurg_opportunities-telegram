import json
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY as PgArray
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.core.enums import Category, OpportunityStatus
from src.db.base import Base

# Reference existing DB enums without auto-creating them
_category_type = PgEnum(Category, name="category", create_type=False)
_status_type = PgEnum(OpportunityStatus, name="opportunitystatus", create_type=False)


class StringList(TypeDecorator):
    """list[str] stored as a native ARRAY on Postgres, JSON text elsewhere (e.g. SQLite)."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgArray(String))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return json.dumps(value or [])

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return json.loads(value) if value else []


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_status", "status"),
        Index("ix_opportunities_similarity_hash", "similarity_hash"),
        Index("ix_opportunities_scheduled_at", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="SET NULL")
    )

    # Extracted fields
    title: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[Category | None] = mapped_column(_category_type)
    deadline: Mapped[str | None] = mapped_column(String(200))
    eligibility: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(300))
    cost: Mapped[str | None] = mapped_column(String(300))
    organizer: Mapped[str | None] = mapped_column(String(300))
    duration: Mapped[str | None] = mapped_column(String(200))
    rewards: Mapped[str | None] = mapped_column(Text)
    apply_link: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    rewritten_text: Mapped[str | None] = mapped_column(Text)

    # Short, AI-written text purpose-built for the card image (see ADR-006 follow-up:
    # avoids blindly slicing long field values, which left "…" on the rendered card).
    card_summary: Mapped[str | None] = mapped_column(Text)
    card_eligibility: Mapped[str | None] = mapped_column(Text)
    card_rewards: Mapped[str | None] = mapped_column(Text)
    # Facts that don't fit a dedicated column (acceptance rate, contact email, etc.)
    # and links beyond apply_link — both exist so splitting a bundled message into
    # multiple opportunities never silently drops information.
    extra_notes: Mapped[str | None] = mapped_column(Text)
    additional_links: Mapped[list[str]] = mapped_column(StringList(), default=list, nullable=False)
    # Verbatim excerpt of just this opportunity from the raw message, used as
    # live_background.py's image-prompt context instead of the whole (possibly
    # multi-opportunity) raw text.
    source_excerpt: Mapped[str | None] = mapped_column(Text)

    # Meta
    media_path: Mapped[str | None] = mapped_column(Text)
    similarity_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[OpportunityStatus] = mapped_column(
        _status_type,
        default=OpportunityStatus.pending,
        nullable=False,
    )
    hooks: Mapped[list[str]] = mapped_column(StringList(), default=list, nullable=False)
    scheduled_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    raw_message: Mapped["RawMessage | None"] = relationship(back_populates="opportunities")
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        secondary="opportunity_tags", back_populates="opportunities"
    )
