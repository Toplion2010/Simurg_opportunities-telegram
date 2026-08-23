"""Enrichment step: fetches each posted-candidate hackathon's detail page
for richer fields than listing endpoints provide. Runs only on the items
that survive filtering + the seen.json check (typically <15 per run) —
never the full listing. Enrichment failure never drops a hackathon: on
any exception the item passes through with its listing-level fields
intact.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from datetime import date

import config
from pipeline.dedup import dedup_key
from pipeline.state import ENRICHED_STATE_PATH
from pipeline.state import load as load_cache
from pipeline.state import prune as prune_cache
from pipeline.state import save as save_cache
from sources import get_source_class
from sources.base import Hackathon, Source

logger = logging.getLogger(__name__)


def _cache_entry(h: Hackathon) -> dict:
    return {
        "ends_at": h.ends_at.isoformat() if h.ends_at else None,
        "description": h.description,
        "prize_breakdown": h.prize_breakdown,
        "eligibility": h.eligibility,
        "required_tech": h.required_tech,
        "deadline": h.deadline.isoformat() if h.deadline else None,
        "sponsors": h.sponsors,
    }


def _apply_cache_entry(h: Hackathon, entry: dict) -> Hackathon:
    deadline_str = entry.get("deadline")
    deadline = date.fromisoformat(deadline_str) if deadline_str else None
    return dataclasses.replace(
        h,
        description=entry.get("description"),
        prize_breakdown=entry.get("prize_breakdown") or [],
        eligibility=entry.get("eligibility"),
        required_tech=entry.get("required_tech") or [],
        deadline=deadline,
        sponsors=entry.get("sponsors") or [],
    )


def _enrich_one(h: Hackathon) -> tuple[Hackathon, bool]:
    """Returns (possibly-enriched hackathon, whether a real detail-page
    fetch was attempted — used to decide whether to sleep). A source with
    no enrich() override (the ABC default) never counts as a fetch."""
    entry = config.SOURCES.get(h.source, {})
    source_cls = get_source_class(entry.get("module", ""))
    if source_cls is None or source_cls.enrich is Source.enrich:
        return h, False

    try:
        return source_cls().enrich(h), True
    except Exception:
        logger.warning(
            "enrich: %s.enrich() failed for %r, passing through unenriched",
            h.source, h.title, exc_info=True,
        )
        return h, True


def enrich(hackathons: list[Hackathon], dry_run: bool = False) -> list[Hackathon]:
    """dry_run controls persistence only, not fetching: dry-run still does
    live detail-page fetches (so --dry-run output reflects real enriched
    content) but never writes the cache to disk."""
    if not config.ENRICH_ENABLED or not hackathons:
        return hackathons

    cache = load_cache(ENRICHED_STATE_PATH)
    result: list[Hackathon] = []
    start = time.monotonic()
    cap_hit = False

    for h in hackathons:
        if not cap_hit and time.monotonic() - start > config.ENRICH_TIMEOUT_TOTAL:
            cap_hit = True
            logger.warning(
                "enrich: total time cap (%.0fs) reached, %d item(s) passing through unenriched",
                config.ENRICH_TIMEOUT_TOTAL, len(hackathons) - len(result),
            )

        if cap_hit:
            result.append(h)
            continue

        key = dedup_key(h)
        cached = cache.get(key)
        if cached is not None:
            result.append(_apply_cache_entry(h, cached))
            continue

        enriched, did_fetch = _enrich_one(h)
        result.append(enriched)
        cache[key] = _cache_entry(enriched)
        if did_fetch:
            time.sleep(config.ENRICH_SLEEP_SECONDS)

    if not dry_run:
        save_cache(prune_cache(cache), ENRICHED_STATE_PATH)

    return result
