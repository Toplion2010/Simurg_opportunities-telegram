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
from pipeline.branding import brand_image, fetch_and_brand_photo
from pipeline.description import split_sentences, summarize
from pipeline.format_prize import summarize_prize
from pipeline.image_gen import generate_image
from pipeline.links import LinkRegistry
from pipeline.reactions import react
from sources.base import Hackathon

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"

REQUIRED_TECH_MAX = 4
THEMES_MAX = 3
DESCRIPTION_SENTENCE_MAX = 3


_BORDERLESS = {"worldwide", "global", "international", "anywhere"}


def _prize_location_line(h: Hackathon) -> str | None:
    prize = summarize_prize(h.prize_breakdown, h.prize_text)
    prize_bit = f"\U0001F3C6 {html.escape(prize)}" if prize else None

    location_bit = None
    if h.location and h.location.strip().lower() in _BORDERLESS:
        # Not a place: open to applicants anywhere (often with an online round
        # but an in-person final), so neither 🌐 Online nor 📍 fits.
        location_bit = f"\U0001F30D {html.escape(h.location.strip())}"
    elif h.is_online is True:
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


def _required_core(h: Hackathon, today: date | None = None, link_url: str | None = None) -> str:
    """Title/link, prize+location, deadline — always present when data
    exists, never dropped or truncated by budget. `link_url` is the branded
    redirect (pipeline/links.py) when one was registered; the reader still
    only sees the title."""
    title = html.escape(h.title)
    url = html.escape(link_url or h.url, quote=True)
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


_HASHTAG_STRIP_RE = re.compile(r"[^\w]+")


def _to_hashtag(theme: str) -> str | None:
    """Telegram terminates a hashtag at the first non-word character, so a
    theme like 'Machine Learning/AI' can't just have spaces removed — the
    '/' would silently cut it short and leave '/AI' dangling as plain text.
    Strip every non-word character instead."""
    cleaned = _HASHTAG_STRIP_RE.sub("", theme)
    return f"#{html.escape(cleaned)}" if cleaned else None


def _themes_line(h: Hackathon) -> str | None:
    if not h.themes:
        return None
    tags = [_to_hashtag(t) for t in h.themes[:THEMES_MAX]]
    tags = [t for t in tags if t]
    return " ".join(tags) if tags else None


LINKS_MAX = 3


def _links_line(h: Hackathon) -> str | None:
    """Built entirely from validated (label, url) pairs — never from raw
    text a model might return — so there's no HTML-injection risk here."""
    if not h.links:
        return None
    anchors = []
    for item in h.links[:LINKS_MAX]:
        if not isinstance(item, dict):
            continue
        label, url = item.get("label"), item.get("url")
        if not label or not url or not str(url).startswith(("http://", "https://")):
            continue
        safe_label = html.escape(str(label))
        safe_url = html.escape(str(url), quote=True)
        anchors.append(f'<a href="{safe_url}">{safe_label}</a>')
    if not anchors:
        return None
    return "\U0001F517 " + " · ".join(anchors)


def footer_text(checked_on: date | None = None, handle: str | None = None) -> str:
    """Light attribution that travels with a copied post. The date is the day
    the post went out — when Simurg last confirmed the listing was live."""
    checked_on = checked_on or date.today()
    handle = config.CHANNEL_HANDLE if handle is None else handle
    lines = [f"✓ Checked by Simurg · {checked_on.day} {checked_on.strftime('%b')}"]
    if handle:
        lines.append(html.escape(handle))
    return "\n".join(lines)


def _assemble(core: str, eligibility: str | None, organizer: str | None,
              themes: str | None, links: str | None, description: str | None,
              footer: str | None = None) -> str:
    parts = [core]
    for line in (eligibility, organizer, themes, links):
        if line:
            parts.append(line)
    text = "\n".join(parts)
    if description:
        text += f"\n\n{description}"
    if footer:
        text += f"\n\n{footer}"
    return text


def format_message(h: Hackathon, max_length: int = 4096, link_url: str | None = None,
                   checked_on: date | None = None, footer: bool = True,
                   handle: str | None = None) -> str:
    """Builds the HTML message/caption text. `max_length` differs by send
    path: 1024 for a sendPhoto caption, 4096 for a plain sendMessage text.
    Any line whose data is missing is omitted entirely — never an empty
    label or bare emoji. When over budget, drops in this order: themes ->
    organizer -> links -> eligibility -> description (truncated, then
    dropped). Title, link, prize, and deadline are never dropped.
    Description is kept as long as possible since it's the most
    informative optional field. It always ends on a complete sentence
    (pipeline/description.py) and never gains an ellipsis it didn't have.
    The attribution footer is part of the never-dropped set."""
    core = _required_core(h, link_url=link_url)
    tail = footer_text(checked_on, handle) if footer else None
    eligibility = _eligibility_line(h)
    organizer = _organizer_line(h)
    themes = _themes_line(h)
    links = _links_line(h)
    plain_description = summarize(h.description, DESCRIPTION_SENTENCE_MAX)
    description = html.escape(plain_description) if plain_description else None

    def build(desc: str | None = description) -> str:
        return _assemble(core, eligibility, organizer, themes, links, desc, tail)

    candidate = build()
    if len(candidate) <= max_length:
        return candidate

    # 1. Drop themes.
    themes = None
    candidate = build()
    if len(candidate) <= max_length:
        return candidate

    # 2. Drop organizer.
    organizer = None
    candidate = build()
    if len(candidate) <= max_length:
        return candidate

    # 3. Drop links.
    links = None
    candidate = build()
    if len(candidate) <= max_length:
        return candidate

    # 4. Drop eligibility.
    eligibility = None
    candidate = build()
    if len(candidate) <= max_length:
        return candidate

    # 5. Shorten the description one whole sentence at a time, then drop it.
    # Every sentence summarize() kept is complete, so any prefix is too.
    if plain_description:
        sentences = split_sentences(plain_description)
        for count in range(len(sentences) - 1, 0, -1):
            candidate = build(html.escape(" ".join(sentences[:count])))
            if len(candidate) <= max_length:
                return candidate
        candidate = build(None)
        if len(candidate) <= max_length:
            return candidate

    # 6. Last resort; core + footer (title/link/prize/deadline) is never
    # truncated in practice, but is hard-capped here as a safety net.
    with_footer = f"{core}\n\n{tail}" if tail else core
    return with_footer if len(with_footer) <= max_length else core[:max_length]


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


def send_message_returning_id(
    token: str, chat_id: str, text: str, disable_preview: bool = False
) -> int | None:
    """Send a plain text message, returning its message_id (needed to pin or
    later edit it). None on failure."""
    response = _post(
        f"bot{token}/sendMessage",
        {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        },
    )
    if response is None:
        return None
    if not response.ok:
        logger.error("telegram: sendMessage failed (%s): %s", response.status_code, response.text)
        return None
    try:
        return response.json()["result"]["message_id"]
    except (ValueError, KeyError):
        logger.error("telegram: sendMessage returned no message_id: %s", response.text[:300])
        return None


def send_message(token: str, chat_id: str, text: str) -> bool:
    """Send a plain text message. Returns True on success."""
    return send_message_returning_id(token, chat_id, text) is not None


def edit_message(token: str, chat_id: str, message_id: int, text: str,
                 disable_preview: bool = False) -> bool:
    """Rewrite an already-posted message in place — how the pinned navigation
    post gets updated without unpinning or re-posting it."""
    response = _post(
        f"bot{token}/editMessageText",
        {
            "chat_id": chat_id, "message_id": message_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": disable_preview,
        },
    )
    if response is None:
        return False
    if not response.ok:
        logger.error("telegram: editMessageText failed (%s): %s", response.status_code, response.text)
        return False
    return True


def pin_message(token: str, chat_id: str, message_id: int) -> bool:
    """Pin silently — a pin notification to every subscriber is noise for a
    reference post they can find at the top anyway."""
    response = _post(
        f"bot{token}/pinChatMessage",
        {"chat_id": chat_id, "message_id": message_id, "disable_notification": True},
    )
    if response is None:
        return False
    if not response.ok:
        logger.error("telegram: pinChatMessage failed (%s): %s", response.status_code, response.text)
        return False
    return True


CHAT_DESCRIPTION_MAX = 255


def set_chat_description(token: str, chat_id: str, description: str) -> bool:
    """Set the channel's About text. Telegram caps this at 255 characters and
    rejects the whole call if it's longer, so it's enforced here."""
    if len(description) > CHAT_DESCRIPTION_MAX:
        logger.error(
            "telegram: description is %d chars, max is %d",
            len(description), CHAT_DESCRIPTION_MAX,
        )
        return False
    response = _post(
        f"bot{token}/setChatDescription", {"chat_id": chat_id, "description": description}
    )
    if response is None:
        return False
    if not response.ok:
        logger.error("telegram: setChatDescription failed (%s): %s", response.status_code, response.text)
        return False
    return True


def send_photo(token: str, chat_id: str, photo_url: str, caption: str) -> int | None:
    """Send a photo by URL with an HTML caption. Returns its message_id on
    success (so callers can react to it), None on failure — callers should
    fall back to send_message on failure (Telegram rejects some remote
    image URLs it can't fetch or decode)."""
    response = _post(
        f"bot{token}/sendPhoto",
        {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
    )
    if response is None:
        return None
    if not response.ok:
        logger.warning("telegram: sendPhoto failed (%s): %s", response.status_code, response.text)
        return None
    try:
        return response.json()["result"]["message_id"]
    except (ValueError, KeyError):
        logger.error("telegram: sendPhoto returned no message_id: %s", response.text[:300])
        return None


def send_photo_bytes(token: str, chat_id: str, photo_bytes: bytes, caption: str) -> int | None:
    """Send a photo uploaded as raw bytes (a generated image, not a URL)
    with an HTML caption. Returns its message_id on success, None on
    failure."""
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
                return None
            try:
                return response.json()["result"]["message_id"]
            except (ValueError, KeyError):
                logger.error(
                    "telegram: sendPhoto (bytes) returned no message_id: %s", response.text[:300]
                )
                return None
        except requests.RequestException:
            logger.warning("telegram: sendPhoto (bytes) request failed on attempt %d", attempt + 1, exc_info=True)
            time.sleep(config.REQUEST_BACKOFF_SECONDS * (2**attempt))

    logger.error("telegram: giving up on sendPhoto (bytes) after retries")
    return None


def send_hackathon(token: str, chat_id: str, h: Hackathon, gemini_api_key: str | None = None,
                   link_url: str | None = None, checked_on: date | None = None) -> bool:
    """Always tries a generated image first — when the source gave a real
    photo, generate_image() uses it as a style reference rather than
    skipping generation, so posts look designed instead of using whatever
    generic thumbnail the source happened to provide. Falls back to the
    real photo verbatim, then to text-only, never costing a post.

    Every image that goes out carries Simurg branding (pipeline/branding.py);
    branding itself is best-effort and falls back to the unbranded image.

    Reacts to whichever message actually landed — a small engagement boost,
    best-effort and never able to turn a successful post into a failure."""
    checked_on = checked_on or date.today()
    caption = format_message(h, max_length=1024, link_url=link_url, checked_on=checked_on)

    if config.IMAGE_GEN_ENABLED and gemini_api_key:
        generated = generate_image(h, gemini_api_key)
        if generated:
            message_id = send_photo_bytes(token, chat_id, brand_image(generated, checked_on), caption)
            if message_id is not None:
                react(token, chat_id, message_id)
                return True

    if h.image_url:
        branded = fetch_and_brand_photo(h.image_url, checked_on)
        if branded:
            message_id = send_photo_bytes(token, chat_id, branded, caption)
        else:
            message_id = send_photo(token, chat_id, h.image_url, caption)
        if message_id is not None:
            react(token, chat_id, message_id)
            return True

    text = format_message(h, max_length=4096, link_url=link_url, checked_on=checked_on)
    message_id = send_message_returning_id(token, chat_id, text)
    if message_id is None:
        return False
    react(token, chat_id, message_id)
    return True


def post_hackathons(
    token: str, chat_id: str, hackathons: list[Hackathon], gemini_api_key: str | None = None,
    links: LinkRegistry | None = None,
) -> list[Hackathon]:
    """Post up to config.MAX_POSTS_PER_RUN hackathons, sleeping between
    sends. Returns the subset actually posted (so callers only mark those
    as seen — the rest go out next run).

    `links` mints the branded title URL per post; without one (or when the
    database is unreachable) posts link straight to the organizer."""
    posted: list[Hackathon] = []
    checked_on = date.today()
    for h in hackathons[: config.MAX_POSTS_PER_RUN]:
        link_url = links.branded_url(h) if links else None
        if send_hackathon(token, chat_id, h, gemini_api_key, link_url=link_url, checked_on=checked_on):
            posted.append(h)
        time.sleep(config.POST_SLEEP_SECONDS)
    return posted
