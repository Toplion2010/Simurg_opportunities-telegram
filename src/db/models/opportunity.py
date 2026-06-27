from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.core.enums import Category, OpportunityStatus
from src.db.base import Base

# Reference existing DB enums without auto-creating them
_category_type = PgEnum(Category, name="category", create_type=False)
_status_type = PgEnum(OpportunityStatus, name="opportunitystatus", create_type=False)


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

    # Meta
    media_path: Mapped[str | None] = mapped_column(Text)
    similarity_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[OpportunityStatus] = mapped_column(
        _status_type,
        default=OpportunityStatus.pending,
        nullable=False,
    )
    hooks: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    scheduled_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    raw_message: Mapped["RawMessage | None"] = relationship(back_populates="opportunity")
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        secondary="opportunity_tags", back_populates="opportunities"
    )
