from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


KIND_TELEGRAM = "telegram"
KIND_WEB = "web"


class SourceChannel(Base):
    """A source Simurg collects from. Two kinds share this table.

    'telegram' rows are identified by telegram_id and advance through history
    with the integer last_seen_msg_id cursor. 'web' rows are identified by
    `identifier` (the scraper's registry key) and carry an opaque JSON string
    in `cursor` instead, because an HTTP catalog has no monotonic message id
    to walk — see src/collector/web/fetcher.py.

    The table keeps its Telegram-era name on purpose: renaming it would touch
    the collector, the repositories, the bot and three workflows for no
    functional gain.
    """

    __tablename__ = "source_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable since 0006: a web source has no Telegram id. Still UNIQUE, and
    # Postgres allows many NULLs in a unique column, so web rows don't collide.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    kind: Mapped[str] = mapped_column(
        String(16), default=KIND_TELEGRAM, server_default=KIND_TELEGRAM, nullable=False
    )
    # Registry key for kind='web' (e.g. 'extracurricularhub'). NULL for Telegram.
    identifier: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    category_hint: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Highest Telegram message id already pulled from this channel. Lets a scheduled
    # run fetch only what was posted since last time, instead of needing a process
    # listening live for new-message events.
    last_seen_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    # Opaque per-source resume token for kind='web'. Each scraper owns its own
    # encoding (a seen-slug set, a modified-since timestamp) and the collector
    # never interprets it.
    cursor: Mapped[str | None] = mapped_column(Text)

    raw_messages: Mapped[list["RawMessage"]] = relationship(  # noqa: F821
        back_populates="source_channel"
    )
