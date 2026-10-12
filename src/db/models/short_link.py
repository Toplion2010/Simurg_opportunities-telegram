from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db.base import Base


class ShortLink(Base):
    """A branded redirect: PUBLIC_BASE_URL/<slug> -> destination_url.

    Written by hackathon-watcher when it posts (plain SQL over psycopg, it does
    not import this package); read by the Vercel function in api/index.py.
    The slug is stable forever once posted -- old Telegram posts keep linking
    to it -- so destination_url may be corrected later but the slug never is.
    """

    __tablename__ = "short_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    destination_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    # 'hackathon' today; leaves room for other channels to share the table.
    kind: Mapped[str] = mapped_column(String(30), nullable=False, server_default="hackathon")
    source: Mapped[str | None] = mapped_column(String(50))
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_clicked_at: Mapped[datetime | None] = mapped_column()


class LinkClick(Base):
    """One row per human click. Deliberately only a timestamp: no IP, no user
    agent, nothing that identifies the person clicking."""

    __tablename__ = "link_clicks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    link_id: Mapped[int] = mapped_column(
        ForeignKey("short_links.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clicked_at: Mapped[datetime] = mapped_column(server_default=func.now())
