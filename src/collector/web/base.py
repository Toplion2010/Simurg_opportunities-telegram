"""The contract every scraped opportunity catalog implements.

Deliberately modelled on hackathon-watcher/sources/base.py, which has been
running in production against 11 sites: one dataclass of listing fields, one
ABC, every failure caught inside the source so a single broken site degrades to
zero yield instead of aborting the run.

The one structural difference is the two-stage fetch. `discover()` is cheap
(one sitemap or index request) and returns candidate ids; the collector then
asks the database which of those it already has and calls `fetch()` for only
the new ones. That is what keeps a 1,760-URL catalog polite and what keeps the
resume cursor small — "what have I seen" is answered from the rows that exist,
never from a parallel set that could drift out of sync with them.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WebItem:
    """One listing, as the catalog states it. No inference, no defaults that
    pretend to be facts: a field the source does not state stays None, and the
    admission filter and DTO builder both treat None as unknown rather than as
    a negative.
    """

    source: str
    external_id: str
    title: str
    page_url: str
    # The OFFICIAL site for the opportunity, when the catalog exposes it.
    # Load-bearing for dedup: Simurg hashes normalized(title) + normalized(
    # apply_link), so pointing this at the real destination is what lets a
    # scraped listing collide with the same opportunity posted on Telegram.
    # Pointing it at the catalog page instead would defeat that silently.
    apply_url: str | None = None
    description: str | None = None
    organizer: str | None = None
    deadline: str | None = None
    starts_at: str | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None
    cost_text: str | None = None
    eligibility: str | None = None
    duration: str | None = None
    country: str | None = None
    is_online: bool | None = None
    grades: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    image_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class WebSource(ABC):
    """A scraped catalog.

    Implementations must:
      1. define `name`, matching their key in registry.WEB_SOURCES;
      2. take no required constructor arguments;
      3. NEVER raise from discover() or fetch() — catch, log, return empty.
         One site changing its markup must not cost the rest of the run.
    """

    name: str

    @abstractmethod
    def discover(self) -> list[str]:
        """Candidate external ids, cheaply. Newest-first where the source
        exposes an order, since the collector truncates to a per-run cap."""

    @abstractmethod
    def fetch(self, external_ids: list[str]) -> list[WebItem]:
        """Build items for these ids. May issue one request per id, so the
        collector only ever passes it a capped list."""
