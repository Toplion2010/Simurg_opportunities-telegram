from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class SourceChannel(Base):
    __tablename__ = "source_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    category_hint: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Highest Telegram message id already pulled from this channel. Lets a scheduled
    # run fetch only what was posted since last time, instead of needing a process
    # listening live for new-message events.
    last_seen_msg_id: Mapped[int | None] = mapped_column(BigInteger)

    raw_messages: Mapped[list["RawMessage"]] = relationship(  # noqa: F821
        back_populates="source_channel"
    )
