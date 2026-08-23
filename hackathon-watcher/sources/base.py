"""Shared data model and interface every source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Hackathon:
    source: str  # 'devpost' | 'devevents' | 'mlh' | 'devfolio' | 'reskilll'
    source_id: str  # stable per-source id
    title: str
    url: str
    starts_at: date | None
    ends_at: date | None
    is_online: bool | None
    prize_text: str | None
    location: str | None
    image_url: str | None = None
    organizer: str | None = None
    themes: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    # --- enrichment (detail-page fields, populated post-filter by pipeline/enrich.py) ---
    description: str | None = None
    prize_breakdown: list[str] = field(default_factory=list)
    eligibility: str | None = None
    required_tech: list[str] = field(default_factory=list)
    deadline: date | None = None
    sponsors: list[str] = field(default_factory=list)


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[Hackathon]:
        """Fetch and parse listings. Must never raise — catch internally,
        log, and return [] on any failure so one broken site can't abort
        the run."""
        raise NotImplementedError

    def enrich(self, hackathon: Hackathon) -> Hackathon:
        """Optional: fetch the hackathon's detail page for richer fields
        than the listing endpoint provides. Default no-op — override to
        opt in. Must never raise; callers also wrap this defensively, but
        an override should still fail closed and return the item
        unenriched rather than propagate."""
        return hackathon
