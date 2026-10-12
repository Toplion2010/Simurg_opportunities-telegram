"""Branded redirect links: PUBLIC_BASE_URL/<slug> -> organizer URL + utm_*.

hackathon-watcher mints the slugs (hackathon-watcher/pipeline/links.py) and
writes them to short_links; api/index.py calls into this module to resolve one
and answer with a temporary redirect. Kept free of any Vercel/HTTP types so it
is testable without a server.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# A single path segment the watcher could have produced. Anything else (dots,
# slashes, upper case) is not a slug and never touches the database.
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")

# Paths that mean something else on this deployment. Kept in sync with
# RESERVED_SLUGS in hackathon-watcher/pipeline/links.py so a slug can never
# shadow a real route.
RESERVED_SLUGS = frozenset({"api", "setup", "webhook", "health", "go", "admin", "static"})

# Link-preview fetchers. They still get redirected (so previews render), but
# are not counted as clicks. Telegram's own in-app browser sends a normal
# browser UA; "TelegramBot" is only the preview crawler.
_BOT_UA_RE = re.compile(
    r"bot|crawl|spider|preview|facebookexternalhit|slack|whatsapp|discord|curl|wget|python",
    re.IGNORECASE,
)

# One round trip: bump the counter, log the click, return the destination.
_RESOLVE_AND_COUNT = text(
    """
    WITH hit AS (
        UPDATE short_links
           SET click_count = click_count + 1,
               last_clicked_at = now()
         WHERE slug = :slug
     RETURNING id, destination_url
    ), logged AS (
        INSERT INTO link_clicks (link_id) SELECT id FROM hit
    )
    SELECT destination_url FROM hit
    """
)
_RESOLVE_ONLY = text("SELECT destination_url FROM short_links WHERE slug = :slug")


def extract_slug(path: str) -> str | None:
    """'/codered-orion' -> 'codered-orion'; None for '/', '/api/webhook',
    '/favicon.ico', reserved words, or anything else that is not a slug."""
    candidate = path.split("?", 1)[0].strip("/").lower()
    if not candidate or not SLUG_RE.match(candidate) or candidate in RESERVED_SLUGS:
        return None
    return candidate


def is_bot(user_agent: str | None) -> bool:
    return bool(user_agent) and bool(_BOT_UA_RE.search(user_agent))


def append_utm(url: str, campaign: str | None, source: str, medium: str | None = None) -> str:
    """Append utm_source / utm_medium / utm_campaign to `url`.

    - Existing query params are preserved byte-for-byte (the original query
      string is kept as-is and the new pairs are appended after it), so an
      organizer URL's own encoding is never rewritten.
    - A utm_* key the URL already carries is never overwritten.
    - The fragment survives: ?utm... goes before #section.
    - Non-http(s) or malformed input is returned unchanged.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return url

    present = {key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)}
    wanted = (("utm_source", source), ("utm_medium", medium), ("utm_campaign", campaign))
    additions = [(key, value) for key, value in wanted if value and key not in present]
    if not additions:
        return url

    query = parts.query
    if query and not query.endswith("&"):
        query += "&"
    query += urlencode(additions)
    return urlunsplit(parts._replace(query=query))


async def resolve_slug(
    session_factory: async_sessionmaker[AsyncSession], slug: str, count: bool = True
) -> str | None:
    """Destination URL for `slug`, or None if it is unknown. With count=True
    the click is recorded in the same statement."""
    async with session_factory() as session:
        if count:
            row = (await session.execute(_RESOLVE_AND_COUNT, {"slug": slug})).first()
            await session.commit()
        else:
            row = (await session.execute(_RESOLVE_ONLY, {"slug": slug})).first()
    if row is None:
        return None
    destination = row[0]
    # Only ever redirect to web URLs, whatever ended up in the table.
    if not isinstance(destination, str) or not destination.startswith(("http://", "https://")):
        return None
    return destination
