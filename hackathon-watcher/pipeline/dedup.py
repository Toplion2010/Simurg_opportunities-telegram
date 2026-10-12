"""Cross-source deduplication.

Dedup key = normalized_title + start_date. On collision, keep the entry from
the higher-priority source (config.SOURCE_PRIORITY) and merge in any
non-null fields the winner is missing from the loser.
"""

from __future__ import annotations

import logging

import config
from pipeline.normalize import normalized_title
from sources.base import Hackathon

logger = logging.getLogger(__name__)


def dedup_key(hackathon: Hackathon) -> str:
    return f"{normalized_title(hackathon.title)}|{hackathon.starts_at}"


_ARTICLES = {"the", "a", "an"}


def title_core(title: str) -> str:
    """normalized_title minus bare numbers, so a season label doesn't make
    the same event look new: 'Diamond Challenge 2026–27' and 'Diamond
    Challenge' both become 'diamond challenge'."""
    return " ".join(
        w for w in normalized_title(title).split() if not w.isdigit() and w not in _ARTICLES
    )


def is_new(h: Hackathon, seen: dict) -> bool:
    """True if `h` hasn't been posted. Three guards, any one blocks:

    - dedup_key (title + start date) — the watcher's own posts
    - exact URL — survives a drifted key (tests/test_dedup_url_guard.py)
    - title_core of a MANUAL entry (manual_post.py). A hand-posted event's
      URL is usually not the one an aggregator later lists it under, so only
      the name can match. Deliberately limited to manual entries: for the
      watcher's own posts, same title + different URL stays a new event.
    """
    if dedup_key(h) in seen:
        return False
    if h.url in {v.get("url") for v in seen.values() if v.get("url")}:
        return False
    core = title_core(h.title)
    if core and core in {
        title_core(v["title"]) for v in seen.values() if v.get("manual") and v.get("title")
    }:
        return False
    return True


def _priority(source: str) -> int:
    entry = config.SOURCES.get(source)
    if entry is None:
        return len(config.SOURCES) + 1
    return entry["priority"]


def _merge(winner: Hackathon, loser: Hackathon) -> Hackathon:
    """Fill in any field on winner that is falsy with the loser's value."""
    for field_name in (
        "starts_at", "ends_at", "is_online", "prize_text", "location",
        "image_url", "organizer",
    ):
        if getattr(winner, field_name) is None:
            setattr(winner, field_name, getattr(loser, field_name))
    if not winner.themes:
        winner.themes = loser.themes
    return winner


def dedup(hackathons: list[Hackathon]) -> list[Hackathon]:
    winners: dict[str, Hackathon] = {}

    for hackathon in hackathons:
        key = dedup_key(hackathon)
        existing = winners.get(key)
        if existing is None:
            winners[key] = hackathon
            continue

        if _priority(hackathon.source) < _priority(existing.source):
            winners[key] = _merge(hackathon, existing)
        else:
            winners[key] = _merge(existing, hackathon)

    return list(winners.values())
