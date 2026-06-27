from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

OpportunityTag = Table(
    "opportunity_tags",
    Base.metadata,
    Column("opportunity_id", Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    opportunities: Mapped[list["Opportunity"]] = relationship(  # noqa: F821
        secondary="opportunity_tags", back_populates="tags"
    )
