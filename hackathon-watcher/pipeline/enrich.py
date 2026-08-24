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
import os
import time
from datetime import date

import config
from pipeline.dedup import dedup_key
from pipeline.generic_enrich import generic_enrich
from pipeline.kaggle_enrich import enrich_kaggle, is_kaggle_competition_url
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
        # --- generic_enrich.py fields (only ever set by the fallback path) ---
        "starts_at": h.starts_at.isoformat() if h.starts_at else None,
        "prize_text": h.prize_text,
        "is_online": h.is_online,
        "location": h.location,
        "links": h.links,
    }


def _apply_cache_entry(h: Hackathon, entry: dict) -> Hackathon:
    deadline_str = entry.get("deadline")
    deadline = date.fromisoformat(deadline_str) if deadline_str else None
    cached_starts_at_str = entry.get("starts_at")
    cached_starts_at = date.fromisoformat(cached_starts_at_str) if cached_starts_at_str else None
    cached_ends_at_str = entry.get("ends_at")
    cached_ends_at = date.fromisoformat(cached_ends_at_str) if cached_ends_at_str else None
    return dataclasses.replace(
        h,
        description=entry.get("description"),
        prize_breakdown=entry.get("prize_breakdown") or [],
        eligibility=entry.get("eligibility"),
        required_tech=entry.get("required_tech") or [],
        deadline=deadline,
        sponsors=entry.get("sponsors") or [],
        # generic_enrich.py fields: prefer this run's freshly-fetched listing
        # value over the cached one — the cache only fills what's missing,
        # same "never overwrite good data" rule generic_enrich itself follows.
        starts_at=h.starts_at or cached_starts_at,
        ends_at=h.ends_at or cached_ends_at,
        prize_text=h.prize_text or entry.get("prize_text"),
        is_online=h.is_online if h.is_online is not None else entry.get("is_online"),
        location=h.location or entry.get("location"),
        links=h.links or (entry.get("links") or []),
    )


def _needs_more(h: Hackathon) -> bool:
    """True when neither a description nor a prize figure exists yet —
    the signal that a source's own enrich() (or the lack of one) didn't
    get enough, and the generic fallback should get a shot too."""
    return not h.description and not h.prize_text


def _enrich_one(
    h: Hackathon, gemini_api_key: str | None, firecrawl_api_key: str | None = None
) -> tuple[Hackathon, bool]:
    """Returns (possibly-enriched hackathon, whether a real detail-page
    fetch was attempted — used to decide whether to sleep). A source's own
    enrich(), if it has one, runs first; if it raises or still leaves the
    item thin (no description, no prize — e.g. ethglobal's detail pages
    are JS-only shells its selector-based enrich() can't read), the
    generic fallback (schema.org JSON-LD sniff, then optionally Gemini —
    with Firecrawl rendering for pages too thin even for that) gets a
    second attempt. Both count as a fetch for sleep-pacing purposes."""
    entry = config.SOURCES.get(h.source, {})
    source_cls = get_source_class(entry.get("module", ""))

    if source_cls is None:
        return h, False

    if source_cls.enrich is not Source.enrich:
        try:
            h = source_cls().enrich(h)
        except Exception:
            logger.warning(
                "enrich: %s.enrich() failed for %r, trying generic fallback",
                h.source, h.title, exc_info=True,
            )
        if not _needs_more(h):
            return h, True

    if is_kaggle_competition_url(h.url):
        username, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
        if username and key:
            try:
                return enrich_kaggle(h, username, key), True
            except Exception:
                logger.warning(
                    "enrich: kaggle enrich failed for %r, falling back to generic_enrich",
                    h.title, exc_info=True,
                )

    try:
        return generic_enrich(h, gemini_api_key, firecrawl_api_key), True
    except Exception:
        logger.warning(
            "enrich: generic_enrich failed for %r, passing through unenriched",
            h.title, exc_info=True,
        )
        return h, True


def enrich(
    hackathons: list[Hackathon],
    dry_run: bool = False,
    gemini_api_key: str | None = None,
    firecrawl_api_key: str | None = None,
) -> list[Hackathon]:
    """dry_run controls persistence only, not fetching: dry-run still does
    live detail-page fetches (so --dry-run output reflects real enriched
    content) but never writes the cache to disk. gemini_api_key is only
    used by the generic fallback's AI tier — sources with their own
    enrich() never need it."""
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

        enriched, did_fetch = _enrich_one(h, gemini_api_key, firecrawl_api_key)
        result.append(enriched)
        cache[key] = _cache_entry(enriched)
        if did_fetch:
            time.sleep(config.ENRICH_SLEEP_SECONDS)

    if not dry_run:
        save_cache(prune_cache(cache), ENRICHED_STATE_PATH)

    return result
