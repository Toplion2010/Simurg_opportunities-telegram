"""Kaggle-specific enrichment for mlcontests items hosted on kaggle.com.

Kaggle competition pages are a pure client-rendered SPA — the raw HTML has
no JSON-LD and no server-rendered text (confirmed live: a fetched page is a
~5KB empty shell, just an og:description meta tag with the competition's
one-line subtitle), so the generic JSON-LD/AI enrichment tiers find nothing
there. Kaggle's public API is the only server-side way to get anything real,
but it requires Basic Auth (a free Kaggle account's username + API key —
confirmed live: even a search-only call 401s with no credentials) and its
`competitions/list` endpoint only exposes that same short subtitle, not full
rules/eligibility text (those live behind the logged-in, JS-only website and
have no API surface at all). So this closes a small gap, not the whole one.

Never raises: any auth/network/shape failure just means no extra fields, not
a lost post — callers should fall back to generic_enrich on exception.
"""

from __future__ import annotations

import dataclasses
import logging
import re

import requests

import config
from sources.base import Hackathon

logger = logging.getLogger(__name__)

_API_LIST_URL = "https://www.kaggle.com/api/v1/competitions/list"
_SLUG_RE = re.compile(r"kaggle\.com/competitions/([^/?#]+)")


def is_kaggle_competition_url(url: str | None) -> bool:
    return bool(url and _SLUG_RE.search(url))


def _slug_from_url(url: str) -> str | None:
    match = _SLUG_RE.search(url)
    return match.group(1) if match else None


def enrich_kaggle(hackathon: Hackathon, username: str, key: str) -> Hackathon:
    slug = _slug_from_url(hackathon.url)
    if not slug:
        return hackathon

    response = requests.get(
        _API_LIST_URL,
        params={"search": slug.replace("-", " ")[:50], "pageSize": 20},
        auth=(username, key),
        timeout=config.ENRICH_DETAIL_TIMEOUT,
    )
    response.raise_for_status()
    items = response.json()
    if not isinstance(items, list):
        return hackathon

    match = next((item for item in items if isinstance(item, dict) and item.get("ref") == slug), None)
    if match is None:
        return hackathon

    description = match.get("description")
    if not hackathon.description and isinstance(description, str) and description.strip():
        return dataclasses.replace(hackathon, description=description.strip()[:500])

    return hackathon
