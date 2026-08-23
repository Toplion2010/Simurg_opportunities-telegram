"""Telegram bot HTTP API — plain requests, no library. Sends new hackathons
to a channel, rate-limited and 429-aware. Posts with a cover image via
sendPhoto when a source supplied one, falling back to a plain text message
(link preview instead of an inline photo) if the image fails to send."""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import date

import requests

import config
from pipeline.format_prize import summarize_prize
from pipeline.image_gen import generate_image
from sources.base import Hackathon

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"

REQUIRED_TECH_MAX = 4
THEMES_MAX = 3
DESCRIPTION_SENTENCE_MAX = 2

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _first_sentences(text: str, count: int) -> str:
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return " ".join(sentences[:count]).strip()


def _prize_location_line(h: Hackathon) -> str | None:
    prize = summarize_prize(h.prize_breakdown, h.prize_text)
    prize_bit = f"\U0001F3C6 {html.escape(prize)}" if prize else None

    location_bit = None
    if h.is_online is True:
        location_bit = "\U0001F310 Online"
    elif h.is_online is False:
        loc = h.location if h.location and h.location.strip().lower() != "in-person" else None
        location_bit = f"\U0001F4CD {html.escape(loc)}" if loc else "\U0001F4CD In-person"
    elif h.location:
        location_bit = f"\U0001F4CD {html.escape(h.location)}"

    bits = [b for b in (prize_bit, location_bit) if b]
    return "  ·  ".join(bits) if bits else None


def _deadline_line(h: Hackathon, today: date | None = None) -> str | None:
    target = h.deadline or h.ends_at
    if target is None:
        return None
    today = today or date.today()
    days_left = (target - today).days
    if days_left < 0:
        return None  # filters should have dropped it; never show a negative
    date_str = f"{target.day} {target.strftime('%b')}"
    if days_left == 0:
        return "⏳ Ends today"
    if days_left == 1:
        return f"⏳ Last day · ends {date_str}"
    return f"⏳ {days_left} days left · ends {date_str}"


def _required_core(h: Hackathon, today: date | None = None) -> str:
    """Title/link, prize+location, deadline — always present when data
    exists, never dropped or truncated by budget."""
    title = html.escape(h.title)
    url = html.escape(h.url, quote=True)
    lines = [f'<b><a href="{url}">{title}</a></b>']

    prize_line = _prize_location_line(h)
    if prize_line:
        lines.append(prize_line)

    deadline_line = _deadline_line(h, today)
    if deadline_line:
        lines.append(deadline_line)

    return "\n".join(lines)


def _eligibility_line(h: Hackathon) -> str | None:
    return f"⚠️ {html.escape(h.eligibility)}" if h.eligibility else None


def _organizer_line(h: Hackathon) -> str | None:
    return f"\U0001F3E2 {html.escape(h.organizer)}" if h.organizer else None


def _themes_line(h: Hackathon) -> str | None:
    if not h.themes:
        return None
    tags = " ".join(f"#{html.escape(t).replace(' ', '')}" for t in h.themes[:THEMES_MAX])
    return tags or None


def _assemble(core: str, eligibility: str | None, organizer: str | None,
              themes: str | None, description: str | None) -> str:
    parts = [core]
    for line in (eligibility, organizer, themes):
        if line:
            parts.append(line)
    text = "\n".join(parts)
    if description:
        text += f"\n\n{description}"
    return text


def format_message(h: Hackathon, max_length: int = 4096) -> str:
    """Builds the HTML message/caption text. `max_length` differs by send
    path: 1024 for a sendPhoto caption, 4096 for a plain sendMessage text.
    Any line whose data is missing is omitted entirely — never an empty
    label or bare emoji. When over budget, drops in this order: description
    (truncated first, then dropped entirely) -> organizer -> themes ->
    eligibility. Title, link, prize, and deadline are never dropped."""
    core = _required_core(h)
    eligibility = _eligibility_line(h)
    organizer = _organizer_line(h)
    themes = _themes_line(h)
    description = _first_sentences(h.description, DESCRIPTION_SENTENCE_MAX) if h.description else None
    description = html.escape(description) if description else None

    candidate = _assemble(core, eligibility, organizer, themes, description)
    if len(candidate) <= max_length:
        return candidate

    # 1. Truncate the description to whatever fits before dropping it.
    if description:
        without_desc = _assemble(core, eligibility, organizer, themes, None)
        budget = max_length - len(without_desc) - len("\n\n") - 1  # -1 for the ellipsis
        if budget > 20:
            truncated = description[:budget].rsplit(" ", 1)[0] + "…"
            candidate = _assemble(core, eligibility, organizer, themes, truncated)
            if len(candidate) <= max_length:
                return candidate
        description = None
        candidate = _assemble(core, eligibility, organizer, themes, None)
        if len(candidate) <= max_length:
            return candidate

    # 2. Drop organizer.
    organizer = None
    candidate = _assemble(core, eligibility, organizer, themes, None)
    if len(candidate) <= max_length:
        return candidate

    # 3. Drop themes.
    themes = None
    candidate = _assemble(core, eligibility, organizer, themes, None)
    if len(candidate) <= max_length:
        return candidate

    # 4. Drop eligibility — last resort; core alone (title/link/prize/deadline)
    # is never truncated in practice, but is hard-capped here as a safety net.
    return core[:max_length]


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
    """Send a photo by URL with an HTML caption. Returns True on success —
    callers should fall back to send_message on failure (Telegram rejects
    some remote image URLs it can't fetch or decode)."""
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


def send_photo_bytes(token: str, chat_id: str, photo_bytes: bytes, caption: str) -> bool:
    """Send a photo uploaded as raw bytes (a generated image, not a URL)
    with an HTML caption. Returns True on success."""
    url = f"{API_BASE}/bot{token}/sendPhoto"
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    files = {"photo": ("hackathon.jpg", photo_bytes, "image/jpeg")}

    for attempt in range(3):
        try:
            response = requests.post(
                url, data=data, files=files, timeout=config.REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code == 429:
                retry_after = response.json().get("parameters", {}).get("retry_after", 5)
                logger.warning("telegram: rate limited, sleeping %ss", retry_after)
                time.sleep(retry_after)
                continue
            if not response.ok:
                logger.warning(
                    "telegram: sendPhoto (bytes) failed (%s): %s",
                    response.status_code, response.text,
                )
                return False
            return True
        except requests.RequestException:
            logger.warning("telegram: sendPhoto (bytes) request failed on attempt %d", attempt + 1, exc_info=True)
            time.sleep(config.REQUEST_BACKOFF_SECONDS * (2**attempt))

    logger.error("telegram: giving up on sendPhoto (bytes) after retries")
    return False


def send_hackathon(token: str, chat_id: str, h: Hackathon, gemini_api_key: str | None = None) -> bool:
    if h.image_url:
        caption = format_message(h, max_length=1024)
        if send_photo(token, chat_id, h.image_url, caption):
            return True
    elif config.IMAGE_GEN_ENABLED and gemini_api_key:
        generated = generate_image(h, gemini_api_key)
        if generated:
            caption = format_message(h, max_length=1024)
            if send_photo_bytes(token, chat_id, generated, caption):
                return True

    text = format_message(h, max_length=4096)
    return send_message(token, chat_id, text)


def post_hackathons(
    token: str, chat_id: str, hackathons: list[Hackathon], gemini_api_key: str | None = None
) -> list[Hackathon]:
    """Post up to config.MAX_POSTS_PER_RUN hackathons, sleeping between
    sends. Returns the subset actually posted (so callers only mark those
    as seen — the rest go out next run)."""
    posted: list[Hackathon] = []
    for h in hackathons[: config.MAX_POSTS_PER_RUN]:
        if send_hackathon(token, chat_id, h, gemini_api_key):
            posted.append(h)
        time.sleep(config.POST_SLEEP_SECONDS)
    return posted
