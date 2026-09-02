from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base


class RawMessage(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (
        Index("ix_raw_messages_source_external", "source_channel_id", "external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_channels.id", ondelete="SET NULL")
    )
    # Nullable since 0006 — a scraped item has no Telegram message id. Exactly
    # one of telegram_msg_id / external_id is set, decided by the source's kind.
    telegram_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    # Stable per-source item id for kind='web' (a slug or catalog id). Unique
    # per source, which is what stops a re-crawl re-ingesting the same listing.
    external_id: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source_channel: Mapped["SourceChannel | None"] = relationship(  # noqa: F821
        back_populates="raw_messages"
    )
    opportunities: Mapped[list["Opportunity"]] = relationship(  # noqa: F821
        back_populates="raw_message"
    )
