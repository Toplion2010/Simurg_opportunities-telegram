"""Post a hand-picked opportunity through the same pipeline as the watcher,
and record it so the watcher never posts it again.

    python manual_post.py manual_posts/diamond-challenge-2026-27.json \\
        --channel @simurg_opportunities --channel @simurg_hackathons

The spec is a JSON object with Hackathon fields (title, url, ends_at, ...;
dates as YYYY-MM-DD). Every post gets the same caption style, footer and
branded card as automatic ones; each channel's card and footer carry that
channel's own handle.

Duplicate protection — the reason this exists rather than ad-hoc posting:
  * state/seen.json gets an entry flagged "manual": true, which
    pipeline/dedup.is_new() matches by title core ("Diamond Challenge
    2026–27" also blocks a later "Diamond Challenge" from any source).
  * a short_links row in Neon (when DATABASE_URL is set), which main.py
    checks independently of seen.json.
seen.json lives in git: commit and push it afterwards, or the next Actions
run won't know about this post.

  --record-only   record an already-posted item without posting again
                  (--posted @channel:123 keeps where it went)
  --dry-run       render captions + cards into --out, post/record nothing

Env: TELEGRAM_BOT_TOKEN (or BOT_TOKEN), GEMINI_API_KEY, DATABASE_URL,
SIMURG_PUBLIC_BASE_URL — all optional except the token when posting.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from pipeline.branding import brand_image
from pipeline.dedup import dedup_key, is_new
from pipeline.image_gen import generate_image
from pipeline.links import registry_from_env
from pipeline.normalize import canonicalize_url
from pipeline.state import load as load_seen
from pipeline.state import save as save_seen
from pipeline.telegram import format_message, send_message_returning_id, send_photo_bytes
from sources.base import Hackathon

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("manual_post")

_DATE_FIELDS = ("starts_at", "ends_at", "deadline")


def load_spec(path: Path) -> Hackathon:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in _DATE_FIELDS:
        if data.get(field):
            data[field] = date.fromisoformat(data[field])
    data.setdefault("source", "manual")
    data.setdefault("source_id", path.stem)
    for field in ("starts_at", "ends_at", "is_online", "prize_text", "location"):
        data.setdefault(field, None)
    h = Hackathon(**data)
    h.url = canonicalize_url(h.url) or h.url
    return h


def seen_entry(h: Hackathon, posts: list[dict]) -> dict:
    return {
        "first_seen": date.today().isoformat(),
        "title": h.title,
        "url": h.url,
        "ends_at": (h.deadline or h.ends_at).isoformat() if (h.deadline or h.ends_at) else None,
        "manual": True,
        "posts": posts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", type=Path)
    parser.add_argument("--channel", action="append", default=[],
                        help="public @handle (repeatable); also used for the card/footer branding")
    parser.add_argument("--record-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="post even if already recorded")
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--posted", action="append", default=[], metavar="CHAT:MESSAGE_ID",
                        help="with --record-only: where it was already posted (repeatable)")
    args = parser.parse_args()

    h = load_spec(args.spec)
    seen = load_seen()
    if not args.force and not args.record_only and not is_new(h, seen):
        logger.error("%r is already recorded in seen.json; use --force to post anyway", h.title)
        return 1

    links = registry_from_env(os.environ.get("DATABASE_URL"))
    checked_on = date.today()
    posts: list[dict] = []
    for item in args.posted:
        chat, _, message_id = item.rpartition(":")
        posts.append({"chat": chat, "message_id": int(message_id)})
    try:
        if args.record_only or args.dry_run:
            link_url = None
        else:
            link_url = links.branded_url(h)  # also registers the short link

        if not args.record_only:
            if not args.channel:
                parser.error("--channel is required unless --record-only")
            token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
            if not token and not args.dry_run:
                parser.error("TELEGRAM_BOT_TOKEN / BOT_TOKEN not set")

            raw = generate_image(h, os.environ.get("GEMINI_API_KEY"))
            for handle in args.channel:
                caption = format_message(h, max_length=1024 if raw else 4096,
                                         link_url=link_url, checked_on=checked_on, handle=handle)
                card = brand_image(raw, checked_on, handle=handle) if raw else None
                if args.dry_run:
                    name = handle.lstrip("@")
                    (args.out / f"caption_{name}.txt").write_text(caption, encoding="utf-8")
                    if card:
                        (args.out / f"card_{name}.jpg").write_bytes(card)
                    logger.info("dry-run: rendered %s into %s", handle, args.out)
                    continue
                message_id = (send_photo_bytes(token, handle, card, caption) if card
                              else send_message_returning_id(token, handle, caption))
                if message_id is None:
                    logger.error("posting to %s failed", handle)
                    continue
                posts.append({"chat": handle, "message_id": message_id})
                logger.info("posted to %s: message %s", handle, message_id)

        if args.dry_run:
            return 0
        if not args.record_only and not posts:
            logger.error("nothing was posted; not recording")
            return 1

        if args.record_only:
            links.slug_for(h)  # registers the short link so Neon knows too
        seen[dedup_key(h)] = seen_entry(h, posts)
        save_seen(seen)
        logger.info("recorded %r in seen.json — commit and push it", h.title)
        return 0
    finally:
        links.close()


if __name__ == "__main__":
    sys.exit(main())
