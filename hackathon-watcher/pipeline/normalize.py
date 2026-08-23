"""Title normalization used as the dedup key's text component, and URL
canonicalization applied pipeline-wide."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")
_NOISE_WORDS = {"hackathon", "hackathons", "hack"}
_YEAR_RE = re.compile(r"\b20\d{2}\b")


def normalized_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, drop noise words
    (trailing year, 'hackathon', etc.) so the same event listed under
    slightly different titles on different sites still collides."""
    text = title.lower()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = _YEAR_RE.sub(" ", text)
    words = [w for w in text.split() if w not in _NOISE_WORDS]
    return _WHITESPACE_RE.sub(" ", " ".join(words)).strip()


def canonicalize_url(url: str) -> str:
    """Strip query string and fragment, strip trailing slash, lowercase the
    host. Applied to every source's url before dedup so links are clean and
    per-source ids that key off raw url stay stable run-to-run."""
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), path, "", ""))
