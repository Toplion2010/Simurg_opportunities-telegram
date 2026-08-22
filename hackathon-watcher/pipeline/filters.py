"""Individually toggleable filters, each reading its threshold from config."""

from __future__ import annotations

import logging
import re
from datetime import date

import config
from sources.base import Hackathon

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")


def online_only(hackathons: list[Hackathon]) -> list[Hackathon]:
    if not config.ONLINE_ONLY:
        return hackathons
    return [h for h in hackathons if h.is_online is not False]


def still_open(hackathons: list[Hackathon]) -> list[Hackathon]:
    if not config.STILL_OPEN:
        return hackathons
    today = date.today()
    return [h for h in hackathons if h.ends_at is None or h.ends_at >= today]


def _parse_prize(prize_text: str | None) -> float | None:
    if not prize_text:
        return None
    match = _PRICE_RE.search(prize_text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def min_prize(hackathons: list[Hackathon]) -> list[Hackathon]:
    if config.MIN_PRIZE is None:
        return hackathons
    result = []
    for h in hackathons:
        amount = _parse_prize(h.prize_text)
        if amount is None or amount >= config.MIN_PRIZE:
            result.append(h)
    return result


def exclude_themes(hackathons: list[Hackathon]) -> list[Hackathon]:
    if not config.EXCLUDE_THEMES:
        return hackathons
    excluded = {t.lower() for t in config.EXCLUDE_THEMES}
    return [
        h for h in hackathons
        if not excluded.intersection(t.lower() for t in h.themes)
    ]


def include_themes(hackathons: list[Hackathon]) -> list[Hackathon]:
    if not config.INCLUDE_THEMES:
        return hackathons
    included = {t.lower() for t in config.INCLUDE_THEMES}
    return [
        h for h in hackathons
        if included.intersection(t.lower() for t in h.themes)
    ]


ALL_FILTERS = [online_only, still_open, min_prize, exclude_themes, include_themes]


def apply_filters(hackathons: list[Hackathon]) -> list[Hackathon]:
    result = hackathons
    for filter_fn in ALL_FILTERS:
        before = len(result)
        result = filter_fn(result)
        logger.info("%s: %d -> %d", filter_fn.__name__, before, len(result))
    return result
