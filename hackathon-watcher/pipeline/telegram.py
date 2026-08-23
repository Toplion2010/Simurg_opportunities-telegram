"""Telegram bot HTTP API — plain requests, no library. Sends new hackathons
to a channel, rate-limited and 429-aware. Posts with a cover image via
sendPhoto when a source supplied one, falling back to a plain text message
(link preview instead of an inline photo) if the image fails to send."""

from __future__ import annotations

import html
import logging
import time

import requests

import config
from sources.base import Hackathon

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def format_message(h: Hackathon) -> str:
    title = html.escape(h.title)
    url = html.escape(h.url, quote=True)
    lines = [f'<b><a href="{url}">{title}</a></b>']

    if h.organizer:
        lines.append(f"\U0001F3E2 {html.escape(h.organizer)}")

    if h.starts_at or h.ends_at:
        start = html.escape(str(h.starts_at)) if h.starts_at else "?"
        end = html.escape(str(h.ends_at)) if h.ends_at else "?"
        lines.append(f"\U0001F4C5 {start} → {end}")

    location_bits = []
    if h.is_online is True:
        location_bits.append("Online")
    elif h.is_online is False:
        location_bits.append("In-person")
    if h.location and h.location.strip().lower() not in ("online", "in-person"):
        location_bits.append(html.escape(h.location))
    if location_bits:
        lines.append(f"\U0001F4CD {' · '.join(location_bits)}")

    if h.prize_text:
        lines.append(f"\U0001F3C6 {html.escape(h.prize_text)}")

    if h.themes:
        lines.append(" ".join(f"#{html.escape(t).replace(' ', '')}" for t in h.themes))

    return "\n".join(lines)


def _post(method: str, payload: dict) -> requests.Response | None:
    url = f"{API_BASE}/{method}"
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 429:
                retry_after = response.json().get("parameters", {}).get("retry_after", 5)
                logger.warning("telegram: rate limited, sleeping %ss", retry_after)
                time.sleep(retry_after)
                continue
            return response
        except requests.RequestException:
            logger.warning("telegram: request failed on attempt %d", attempt + 1, exc_info=True)
            time.sleep(config.REQUEST_BACKOFF_SECONDS * (2**attempt))

    logger.error("telegram: giving up after retries")
    return None


def send_message(token: str, chat_id: str, text: str) -> bool:
    """Send a plain text message. Returns True on success."""
    response = _post(
        f"bot{token}/sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
    )
    if response is None:
        return False
    if not response.ok:
        logger.error("telegram: sendMessage failed (%s): %s", response.status_code, response.text)
        return False
    return True


def send_photo(token: str, chat_id: str, photo_url: str, caption: str) -> bool:
    """Send a photo with an HTML caption. Returns True on success — callers
    should fall back to send_message on failure (Telegram rejects some
    remote image URLs it can't fetch or decode)."""
    response = _post(
        f"bot{token}/sendPhoto",
        {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
    )
    if response is None:
        return False
    if not response.ok:
        logger.warning("telegram: sendPhoto failed (%s): %s", response.status_code, response.text)
        return False
    return True


def send_hackathon(token: str, chat_id: str, h: Hackathon) -> bool:
    text = format_message(h)
    if h.image_url and send_photo(token, chat_id, h.image_url, text):
        return True
    return send_message(token, chat_id, text)


def post_hackathons(token: str, chat_id: str, hackathons: list[Hackathon]) -> list[Hackathon]:
    """Post up to config.MAX_POSTS_PER_RUN hackathons, sleeping between
    sends. Returns the subset actually posted (so callers only mark those
    as seen — the rest go out next run)."""
    posted: list[Hackathon] = []
    for h in hackathons[: config.MAX_POSTS_PER_RUN]:
        if send_hackathon(token, chat_id, h):
            posted.append(h)
        time.sleep(config.POST_SLEEP_SECONDS)
    return posted
