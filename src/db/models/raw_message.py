from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_channels.id", ondelete="SET NULL")
    )
    telegram_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source_channel: Mapped["SourceChannel | None"] = relationship(  # noqa: F821
        back_populates="raw_messages"
    )
    opportunity: Mapped["Opportunity | None"] = relationship(  # noqa: F821
        back_populates="raw_message"
    )
