"""Orchestrates the hackathon watcher: fetch -> dedup -> filter -> new-only -> post -> persist.

Sources are registered in config.SOURCES, not hardcoded here — adding a
source is one new file plus one dict entry. This module resolves each
entry's module dynamically and never imports a source module by name.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

import config
from pipeline.dedup import dedup, dedup_key
from pipeline.enrich import enrich
from pipeline.filters import apply_filters
from pipeline.normalize import canonicalize_url
from pipeline.state import load as load_seen
from pipeline.state import prune as prune_seen
from pipeline.state import save as save_seen
from pipeline.telegram import post_hackathons
from sources import get_source_class
from sources.base import Hackathon, Source

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")


def _resolve_sources(names: list[str] | None) -> dict[str, type[Source]]:
    """Resolve config.SOURCES entries to classes. `names`, if given, both
    selects and overrides `enabled` (an explicit -r/--resources request
    runs a source even if it's disabled by default)."""
    resolved: dict[str, type[Source]] = {}
    candidates = names if names else [n for n, e in config.SOURCES.items() if e["enabled"]]

    for name in candidates:
        entry = config.SOURCES.get(name)
        if entry is None:
            logger.error("unknown source: %s", name)
            continue
        source_cls = get_source_class(entry["module"])
        if source_cls is not None:
            resolved[name] = source_cls
    return resolved


def fetch_all(names: list[str] | None = None, limit: int | None = None) -> list[Hackathon]:
    """Fetch from every resolved source. `limit`, if given, caps the number
    of items kept per source — a command-layer concern; sources themselves
    take no `limit` parameter. Every url is canonicalized here (tracking
    params stripped, host lowercased) before dedup ever sees it."""
    results: list[Hackathon] = []
    for name, source_cls in _resolve_sources(names).items():
        fetched = source_cls().fetch()
        if limit is not None:
            fetched = fetched[:limit]
        for h in fetched:
            h.url = canonicalize_url(h.url)
        logger.info("%s: fetched %d", name, len(fetched))
        results.extend(fetched)
    return results


def _print_hackathon(h: Hackathon) -> None:
    print(f"- [{h.source}] {h.title}")
    print(f"    url: {h.url}")
    print(f"    dates: {h.starts_at} -> {h.ends_at}  online={h.is_online}")
    print(f"    prize: {h.prize_text}  location: {h.location}")
    print(f"    themes: {h.themes}")
    if h.description:
        print(f"    description: {h.description}")
    if h.prize_breakdown:
        print(f"    prize_breakdown: {h.prize_breakdown}")
    if h.eligibility:
        print(f"    eligibility: {h.eligibility}")
    if h.required_tech:
        print(f"    required_tech: {h.required_tech}")
    if h.sponsors:
        print(f"    sponsors: {h.sponsors}")
    if h.deadline:
        print(f"    deadline: {h.deadline}")


def _seen_entry(h: Hackathon) -> dict:
    return {
        "first_seen": date.today().isoformat(),
        "title": h.title,
        "url": h.url,
        "ends_at": h.ends_at.isoformat() if h.ends_at else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Hackathon watcher bot")
    parser.add_argument(
        "-r", "--resources", nargs="+", metavar="NAME",
        help="run only these sources (by config.SOURCES key)",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="fetch + dedup + filter, print what would be posted, touch nothing",
    )
    parser.add_argument(
        "-l", "--limit", type=int, default=None,
        help="cap items processed per source",
    )
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="ignore seen.json, re-process everything as if new",
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="populate seen.json with everything currently live, without posting",
    )
    parser.add_argument(
        "--no-enrich", action="store_true",
        help="skip the detail-page enrichment step",
    )
    parser.add_argument(
        "--no-image-gen", action="store_true",
        help="skip Gemini fallback image generation, even if GEMINI_API_KEY is set",
    )
    args = parser.parse_args()

    fetched = fetch_all(args.resources, args.limit)
    logger.info("fetched: %d", len(fetched))

    deduped = dedup(fetched)
    logger.info("deduped: %d", len(deduped))

    filtered = apply_filters(deduped)
    logger.info("filtered: %d", len(filtered))

    # `seen` is always the on-disk state and is what gets persisted —
    # --force only changes which items COUNT as new, so it can never wipe
    # out entries for hackathons this run didn't touch.
    seen = load_seen()
    check_against = {} if args.force else seen
    new_items = [h for h in filtered if dedup_key(h) not in check_against]
    logger.info("new: %d", len(new_items))

    if args.seed:
        # Seeds off `filtered` (everything currently live), not `new_items`
        # — enrichment stays skipped here on purpose, since seeding would
        # otherwise pay for detail-page fetches on ~40+ items instead of
        # the handful that would actually get posted on a normal run.
        for h in filtered:
            seen[dedup_key(h)] = _seen_entry(h)
        save_seen(prune_seen(seen))
        logger.info("seeded seen.json with %d entries, nothing posted", len(filtered))
        return

    if config.ENRICH_ENABLED and not args.no_enrich:
        new_items = enrich(new_items, dry_run=args.dry_run)
        logger.info("enriched: %d", len(new_items))

    if args.dry_run:
        print(f"\n{len(new_items)} hackathon(s) would be posted:\n")
        for h in new_items:
            _print_hackathon(h)
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in the environment; "
            "nothing posted, seen.json left untouched"
        )
        return

    gemini_api_key = None if args.no_image_gen else os.environ.get("GEMINI_API_KEY")
    posted = post_hackathons(token, chat_id, new_items, gemini_api_key)
    logger.info("posted: %d / %d new", len(posted), len(new_items))

    for h in posted:
        seen[dedup_key(h)] = _seen_entry(h)
    save_seen(prune_seen(seen))


if __name__ == "__main__":
    main()
