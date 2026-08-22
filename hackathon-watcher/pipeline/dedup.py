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


def _priority(source: str) -> int:
    entry = config.SOURCES.get(source)
    if entry is None:
        return len(config.SOURCES) + 1
    return entry["priority"]


def _merge(winner: Hackathon, loser: Hackathon) -> Hackathon:
    """Fill in any field on winner that is falsy with the loser's value."""
    for field_name in (
        "starts_at", "ends_at", "is_online", "prize_text", "location",
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
