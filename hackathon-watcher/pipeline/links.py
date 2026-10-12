"""Branded post links: the title in every post points at
PUBLIC_BASE_URL/<slug>, which the Vercel function (api/index.py in the repo
root) resolves from Neon's short_links table and 302s to the organizer URL
with utm_* attribution appended.

This module only MINTS links: it turns a title into a readable slug, settles
collisions, and writes the row. Redirecting, click counting and UTM all live
on the Vercel side (src/links/redirect.py), so changing UTM values or moving
to a custom domain never requires re-posting anything.

Fails closed in every direction: no DATABASE_URL, no driver, Neon asleep or
the table not migrated yet -> branded_url() returns the organizer URL and the
post goes out exactly as it did before this existed.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Protocol

import config
from sources.base import Hackathon

logger = logging.getLogger(__name__)

SLUG_MAX = 80

# Must stay in sync with RESERVED_SLUGS in src/links/redirect.py: these paths
# mean something else on the Vercel deployment.
RESERVED_SLUGS = frozenset({"api", "setup", "webhook", "health", "go", "admin", "static"})

# A slug made only of these says nothing about the event, so the organizer is
# added up front instead of waiting for a collision.
_GENERIC_WORDS = frozenset({
    "hackathon", "hackathons", "hack", "challenge", "competition", "contest",
    "online", "global", "virtual", "the", "a", "an", "of", "and", "for",
    "ai", "ml", "web3", "edition", "season", "event", "summit", "jam", "game",
})

_YEAR_RE = re.compile(r"(?:^|-)(?:19|20)\d{2}(?:-|$)")


def slugify(text: str | None, max_length: int = SLUG_MAX) -> str:
    """'CodeRED: Orion' -> 'codered-orion';
    'Financial Cybersecurity Challenge 2026' -> 'financial-cybersecurity-challenge-2026'.
    Accents are folded to ASCII, apostrophes vanish without splitting the
    word (Women's -> womens), '&' and '+' become words, everything else that
    is not a letter or digit becomes a single hyphen. Long titles are cut on
    a word boundary, never mid-word."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"['’`]", "", text)
    text = text.replace("&", " and ").replace("+", " plus ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_length:
        cut = text[:max_length]
        text = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return text.strip("-")


def _is_generic(slug: str) -> bool:
    words = [w for w in slug.split("-") if w and not w.isdigit()]
    return not words or all(w in _GENERIC_WORDS for w in words)


def _join(*parts: str) -> str:
    joined = "-".join(p for p in parts if p)
    return slugify(joined)  # re-trims to SLUG_MAX on a word boundary


def slug_candidates(h: Hackathon, extra_numbered: int = 20) -> list[str]:
    """Preference-ordered slugs for `h`. Collision ladder per the spec:
    plain title -> + year (if not already in it) -> + organizer -> -2, -3 ...
    A title with no ASCII letters at all (e.g. fully CJK) falls back to the
    organizer / source so the URL is still readable."""
    base = slugify(h.title)
    organizer = slugify(h.organizer, max_length=30)
    event_date = h.starts_at or h.ends_at or h.deadline
    year = str(event_date.year) if event_date else ""

    if not base:
        base = _join(organizer, "hackathon") if organizer else _join(h.source, "hackathon")

    if _is_generic(base) and organizer and organizer not in base:
        base = _join(organizer, base)

    candidates = [base]
    if year and not _YEAR_RE.search(base):
        candidates.append(_join(base, year))
    if organizer and organizer not in base:
        candidates.append(_join(base, organizer))
        if year and not _YEAR_RE.search(base):
            candidates.append(_join(base, year, organizer))
    numbered_root = candidates[0]
    candidates.extend(f"{numbered_root}-{n}" for n in range(2, 2 + extra_numbered))

    seen: set[str] = set()
    ordered = []
    for c in candidates:
        if c and c not in seen and c not in RESERVED_SLUGS:
            seen.add(c)
            ordered.append(c)
    return ordered


def public_url(slug: str, base_url: str | None = None) -> str:
    return f"{(base_url or config.PUBLIC_BASE_URL).rstrip('/')}/{slug}"


class LinkStore(Protocol):
    def find_by_url(self, url: str) -> str | None: ...
    def existing_urls(self, urls: list[str]) -> set[str]: ...
    def try_insert(self, slug: str, url: str, title: str, source: str) -> bool: ...


class PostgresLinkStore:
    """short_links over a plain psycopg connection. Lazily connects on first
    use; one connection per watcher run."""

    def __init__(self, database_url: str):
        self._dsn = _to_libpq_dsn(database_url)
        self._conn = None

    def _connection(self):
        if self._conn is None:
            import psycopg  # imported lazily: a missing driver must not break posting

            self._conn = psycopg.connect(self._dsn, connect_timeout=15, autocommit=True)
        return self._conn

    def find_by_url(self, url: str) -> str | None:
        with self._connection().cursor() as cur:
            cur.execute(
                "SELECT slug FROM short_links WHERE destination_url = %s ORDER BY id LIMIT 1",
                (url,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def existing_urls(self, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        with self._connection().cursor() as cur:
            cur.execute(
                "SELECT destination_url FROM short_links WHERE destination_url = ANY(%s)",
                (list(urls),),
            )
            return {row[0] for row in cur.fetchall()}

    def try_insert(self, slug: str, url: str, title: str, source: str) -> bool:
        with self._connection().cursor() as cur:
            cur.execute(
                "INSERT INTO short_links (slug, destination_url, title, kind, source) "
                "VALUES (%s, %s, %s, 'hackathon', %s) "
                "ON CONFLICT (slug) DO NOTHING RETURNING id",
                (slug, url, title, source),
            )
            return cur.fetchone() is not None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None


def _to_libpq_dsn(url: str) -> str:
    """The repo's DATABASE_URL is written for SQLAlchemy+asyncpg
    ('postgresql+asyncpg://...?ssl=require'); libpq wants
    'postgresql://...?sslmode=require'."""
    url = re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql://", url)
    url = re.sub(r"([?&])ssl=", r"\1sslmode=", url)
    return url


class LinkRegistry:
    """Mints and remembers slugs for one run. Disables itself after the first
    database error so a dead connection costs one timeout, not one per post."""

    def __init__(self, store: LinkStore | None, base_url: str | None = None):
        self._store = store
        self._base_url = base_url or config.PUBLIC_BASE_URL
        self._disabled = store is None or not self._base_url

    def slug_for(self, h: Hackathon) -> str | None:
        if self._disabled:
            return None
        try:
            existing = self._store.find_by_url(h.url)
            if existing:
                return existing
            for candidate in slug_candidates(h):
                if self._store.try_insert(candidate, h.url, h.title, h.source):
                    return candidate
            logger.warning("links: no free slug for %r", h.title)
        except Exception:
            logger.warning("links: database unavailable, posting organizer URLs this run",
                           exc_info=True)
            self._disabled = True
        return None

    def posted_urls(self, urls: list[str]) -> set[str]:
        """Which of `urls` already have a short link — i.e. were posted
        before, by the watcher or manual_post.py. Empty set when the DB is
        unavailable (seen.json is then the only guard, as before)."""
        if self._store is None or not urls:
            return set()
        try:
            return self._store.existing_urls(urls)
        except Exception:
            logger.warning("links: duplicate check against short_links failed", exc_info=True)
            self._disabled = True
            return set()

    def branded_url(self, h: Hackathon) -> str:
        """The URL to put behind the post title: the branded redirect when a
        slug could be registered, the organizer URL otherwise."""
        slug = self.slug_for(h)
        return public_url(slug, self._base_url) if slug else h.url

    def close(self) -> None:
        close = getattr(self._store, "close", None)
        if close:
            close()


def registry_from_env(database_url: str | None) -> LinkRegistry:
    if not config.BRANDED_LINKS_ENABLED or not database_url:
        if config.BRANDED_LINKS_ENABLED:
            logger.info("links: DATABASE_URL not set, posting organizer URLs")
        return LinkRegistry(None)
    return LinkRegistry(PostgresLinkStore(database_url))
