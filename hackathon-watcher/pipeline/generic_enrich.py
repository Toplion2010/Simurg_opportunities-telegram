"""Generic enrichment fallback for any source that hasn't defined its own
`enrich()` (currently reskilll, dev.events, MLH, Hack Club Hackathons —
any future source added without a custom scraper gets this automatically),
plus a second-pass fallback for sources whose own enrich() came back empty
(e.g. ethglobal — see pipeline/enrich.py's `_needs_more` check).

Three tiers, cheapest first:

1. Schema.org JSON-LD sniff (free, no API call) — many event sites embed
   a real `Event`/`EducationEvent`/`EventSeries` block regardless of
   platform (confirmed live on reskilll's and dev.events' own pages).
2. Gemini text extraction from the raw fetch (only if tier 1 finds
   nothing, and GEMINI_API_KEY is set) — for sites with no structured
   data at all but real server-rendered text (confirmed on MLH/Hack
   Club's linked organizer sites: hackrice.com, hackmty.com,
   animalhack.org, ... none carry JSON-LD but have plenty of real text).
3. Firecrawl-rendered text + Gemini (only if the raw fetch is a JS-only
   shell — under AI_ENRICH_MIN_PAGE_CHARS of visible text — and
   FIRECRAWL_API_KEY is set) — for pure client-rendered SPAs where even
   the raw HTML has nothing to read (confirmed live on ethglobal.com and
   kaggle.com: ~15-20 visible characters, just the page title).

Only fills fields that are currently empty on the Hackathon — never
overwrites data a source's own listing/enrich already provided. Never
raises: any fetch/parse/API failure just means no extra fields, not a
lost post.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import datetime
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

import config
from pipeline.format_prize import _format_amount
from pipeline.text import strip_markdown
from sources.base import Hackathon
from sources.http import get

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

_LD_JSON_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_PRIZE_NEAR_WORD_RE = re.compile(
    r"[$€£₹][\d,]+(?:\.\d+)?\s*(?:in\s*)?prizes?(?:\s*pool)?", re.IGNORECASE
)
_CURRENCY_CODES = "USD|EUR|GBP|INR|CAD|AUD"
# "Prize Pool 5,000 USD" (DoraHacks) — the amount trails the label and the
# currency trails the amount, so the symbol-first pattern above never sees it.
_PRIZE_LABELLED_RE = re.compile(
    rf"prizes?\s*pool\s*[:\-]?\s*(?:(?P<sym>[$€£₹])\s*(?P<amt1>[\d,]+(?:\.\d+)?)"
    rf"|(?P<amt2>[\d,]+(?:\.\d+)?)\s*(?P<code>{_CURRENCY_CODES})\b)",
    re.IGNORECASE,
)


def _find_prize_in_text(text: str) -> str | None:
    match = _PRIZE_NEAR_WORD_RE.search(text)
    if match:
        return match.group(0).split()[0]
    match = _PRIZE_LABELLED_RE.search(text)
    if match:
        if match.group("sym"):
            return f"{match.group('sym')}{match.group('amt1')}"
        return f"{match.group('code').upper()} {match.group('amt2')}"
    return None

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "nullable": True},
        "prize_amount": {"type": "number", "nullable": True},
        "prize_currency": {"type": "string", "nullable": True},
        "eligibility": {"type": "string", "nullable": True},
        "is_online": {"type": "boolean", "nullable": True},
        "location": {"type": "string", "nullable": True},
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    },
}


def _parse_iso(text: str | None):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


# --- Tier 1: schema.org JSON-LD sniff -------------------------------------


def _find_jsonld_event(html: str) -> dict | None:
    for match in _LD_JSON_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for block in list(candidates):
            if isinstance(block, dict) and isinstance(block.get("@graph"), list):
                candidates = candidates + block["@graph"]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            type_ = candidate.get("@type")
            types = type_ if isinstance(type_, list) else [type_]
            if any(isinstance(t, str) and "event" in t.lower() for t in types):
                return candidate
    return None


def _extract_from_jsonld(event: dict) -> dict:
    fields: dict = {}
    raw_description = event.get("description")
    if raw_description:
        text = BeautifulSoup(str(raw_description), "html.parser").get_text(" ", strip=True)
        # Sites put markdown in this field (DoraHacks ships "# The theme\n\n…"),
        # which would render as literal '#' and '**' in the post.
        text = strip_markdown(text)
        # Aggregators synthesise a "description" from the category and format
        # ("Crypto / Blockchain hackathon Online"), which only repeats what the
        # post already shows. Same floor as devevents.py's own guard.
        if len(text) < config.DESCRIPTION_MIN_CHARS:
            text = ""
        if text:
            fields["description"] = text[:500]
            prize = _find_prize_in_text(text)
            if prize:
                fields["prize_text"] = prize

    mode = event.get("eventAttendanceMode") or ""
    if "Online" in mode:
        fields["is_online"] = True
    elif "Offline" in mode or "Mixed" in mode:
        fields["is_online"] = False

    starts_at = _parse_iso(event.get("startDate"))
    ends_at = _parse_iso(event.get("endDate"))
    if starts_at:
        fields["starts_at"] = starts_at
    if ends_at:
        fields["ends_at"] = ends_at

    return fields


# --- Tier 3: Firecrawl-rendered text (for JS-only pages) ------------------


def _firecrawl_page(url: str, api_key: str) -> tuple[str | None, str]:
    """Returns (visible text, raw html). The html is what lets a wrapper
    page's iframe target be found even when the site blocks this bot's
    own fetches outright."""
    response = requests.post(
        _FIRECRAWL_SCRAPE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"url": url, "formats": ["markdown", "rawHtml"], "onlyMainContent": False},
        timeout=config.FIRECRAWL_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Firecrawl API error {response.status_code}: {response.text[:300]}")
    data = (response.json().get("data") or {})
    raw_html = data.get("rawHtml") or ""
    markdown = data.get("markdown") or ""
    text = re.sub(r"\s+", " ", markdown).strip()[: config.AI_ENRICH_PAGE_CHARS] if markdown.strip() else None
    return text, raw_html


def _firecrawl_page_text(url: str, api_key: str) -> str | None:
    return _firecrawl_page(url, api_key)[0]


# Firecrawl rewrites <iframe> into <div data-original-tag="iframe"> (keeping
# src), so both shapes have to be recognised.
_IFRAME_SELECTOR = 'iframe[src], [data-original-tag="iframe"][src]'

# Ordinary embeds (a promo video, a venue map, a signup form) are not the
# event's real home and must never hijack the posted url.
_EMBED_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "loom.com",
    "google.com", "gstatic.com", "doubleclick.net", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "spotify.com", "soundcloud.com",
    "typeform.com", "airtable.com", "calendly.com", "recaptcha.net",
)


def _wrapper_iframe_target(html: str, page_url: str) -> str | None:
    """Some aggregators (dev.events) serve a shell whose only real content is
    an off-domain iframe of the actual event site. That target is both the
    only readable content and the better link to post."""
    if not html:
        return None
    domain = urlsplit(page_url).netloc
    try:
        candidates = BeautifulSoup(html, "html.parser").select(_IFRAME_SELECTOR)
    except Exception:
        return None
    for tag in candidates:
        src = (tag.get("src") or "").strip()
        if not src.startswith(("http://", "https://")):
            continue
        netloc = urlsplit(src).netloc.lower()
        if not netloc or netloc == domain or netloc.endswith(f".{domain}"):
            continue
        if any(netloc == h or netloc.endswith(f".{h}") for h in _EMBED_HOSTS):
            continue
        return src
    return None


# --- Tier 2: Gemini text extraction ---------------------------------------


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return text[: config.AI_ENRICH_PAGE_CHARS]


def _valid_link(url: str, page_domain: str) -> bool:
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        return parts.netloc == page_domain or parts.netloc.endswith(f".{page_domain}")
    except Exception:
        return False


def _call_gemini_text(prompt: str, api_key: str) -> dict | None:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }
    url = f"{_API_BASE}/{config.GEMINI_TEXT_MODEL}:generateContent?key={api_key}"
    # These calls hang rather than fail fast, and the same page that times out
    # succeeds on a later run, so one fresh attempt recovers most of them.
    for attempt in range(config.AI_ENRICH_ATTEMPTS):
        try:
            response = requests.post(url, json=payload, timeout=config.AI_ENRICH_TIMEOUT)
            break
        except requests.exceptions.Timeout:
            if attempt == config.AI_ENRICH_ATTEMPTS - 1:
                raise
            logger.warning("generic_enrich: Gemini timed out, retrying once")

    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:300]}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    for part in parts:
        text = part.get("text")
        if text:
            return json.loads(text)
    return None


def _extract_via_ai(hackathon: Hackathon, page_text: str, api_key: str) -> dict:
    prompt = (
        "You are extracting factual information about a hackathon or coding "
        "competition from the raw text of its own webpage, given below. "
        "Return null for any field that is not clearly and explicitly stated "
        "on the page — never guess, infer, or invent a value. For 'links', "
        "list at most 3 links to sub-pages clearly relevant to the event "
        "itself (e.g. Rules, Prizes, Schedule, Register) if you can identify "
        "their URLs in the text; omit anything you're not confident about.\n\n"
        f"Hackathon title (for context only, do not repeat it back): {hackathon.title}\n\n"
        f"Page text:\n{page_text}"
    )
    try:
        result = _call_gemini_text(prompt, api_key)
    except Exception:
        logger.warning("generic_enrich: AI extraction failed for %s", hackathon.url, exc_info=True)
        return {}
    if not result:
        return {}

    fields: dict = {}

    description = result.get("description")
    if isinstance(description, str) and description.strip():
        fields["description"] = description.strip()[:500]

    amount = result.get("prize_amount")
    currency = result.get("prize_currency")
    if isinstance(amount, (int, float)) and amount > 0 and isinstance(currency, str) and currency.strip():
        try:
            currency_str = currency.strip()
            sep = "" if len(currency_str) == 1 else " "
            fields["prize_text"] = f"{currency_str}{sep}{_format_amount(float(amount))}"
        except Exception:
            pass

    eligibility = result.get("eligibility")
    if isinstance(eligibility, str) and eligibility.strip():
        fields["eligibility"] = eligibility.strip()[:300]

    if isinstance(result.get("is_online"), bool):
        fields["is_online"] = result["is_online"]

    location = result.get("location")
    if isinstance(location, str) and location.strip():
        fields["location"] = location.strip()

    page_domain = urlsplit(hackathon.url).netloc
    valid_links = []
    for item in result.get("links") or []:
        if len(valid_links) >= 3:
            break
        if not isinstance(item, dict):
            continue
        label, link_url = item.get("label"), item.get("url")
        if not isinstance(label, str) or not isinstance(link_url, str):
            continue
        if not label.strip() or not _valid_link(link_url, page_domain):
            continue
        valid_links.append({"label": label.strip()[:30], "url": link_url})
    if valid_links:
        fields["links"] = valid_links

    return fields


# --- Orchestrator ----------------------------------------------------------


def _load_page(url: str, firecrawl_api_key: str | None) -> str | None:
    """Page html, preferring a plain fetch and falling back to Firecrawl when
    the site blocks this bot outright (dev.events 403s datacenter IPs) or
    serves a JS-only shell. None means nothing readable was obtained."""
    try:
        response = get(url, timeout=config.ENRICH_DETAIL_TIMEOUT, retries=config.ENRICH_DETAIL_RETRIES)
        response.raise_for_status()
        html = response.text
    except Exception:
        if not firecrawl_api_key:
            logger.warning("generic_enrich: fetch failed for %s", url, exc_info=True)
            return None
        logger.warning("generic_enrich: fetch failed for %s, trying Firecrawl render", url)
        html = ""

    if firecrawl_api_key and len(_page_text(html) if html else "") < config.AI_ENRICH_MIN_PAGE_CHARS:
        try:
            _, rendered_html = _firecrawl_page(url, firecrawl_api_key)
            if rendered_html:
                return rendered_html
        except Exception:
            logger.warning("generic_enrich: Firecrawl render failed for %s", url, exc_info=True)

    return html or None


def _extract_all(html: str, hackathon: Hackathon, gemini_api_key: str | None) -> dict:
    """Tier 1 (JSON-LD) then, only if it yielded nothing, Tier 2 (Gemini)."""
    fields: dict = {}
    try:
        event = _find_jsonld_event(html)
        if event:
            fields = _extract_from_jsonld(event)
    except Exception:
        logger.warning("generic_enrich: JSON-LD extraction failed for %s", hackathon.url, exc_info=True)

    if not fields and gemini_api_key and config.AI_ENRICH_ENABLED:
        try:
            text = _page_text(html)
            if text:
                fields = _extract_via_ai(hackathon, text, gemini_api_key)
        except Exception:
            logger.warning("generic_enrich: AI tier failed for %s", hackathon.url, exc_info=True)

    # The prize is often page furniture ("Prize Pool 5,000 USD" in DoraHacks'
    # header) rather than part of any description, so it needs its own sweep
    # over the visible text — free, and it runs whichever tier produced the rest.
    if fields and not fields.get("prize_text"):
        try:
            prize = _find_prize_in_text(_page_text(html))
            if prize:
                fields["prize_text"] = prize
        except Exception:
            logger.warning("generic_enrich: prize sweep failed for %s", hackathon.url, exc_info=True)

    return fields


def generic_enrich(
    hackathon: Hackathon, gemini_api_key: str | None, firecrawl_api_key: str | None = None
) -> Hackathon:
    html = _load_page(hackathon.url, firecrawl_api_key)
    if html is None:
        return hackathon

    fields = _extract_all(html, hackathon, gemini_api_key)

    # No usable description means this page is likely a shell wrapping the
    # real event site in an off-domain iframe (dev.events does exactly this,
    # and the link it would post often renders an error). Follow it once and
    # prefer whatever the real page yields.
    if not fields.get("description"):
        target = _wrapper_iframe_target(html, hackathon.url)
        if target:
            logger.info("generic_enrich: following wrapper iframe %s -> %s", hackathon.url, target)
            target_html = _load_page(target, firecrawl_api_key)
            if target_html:
                hackathon = dataclasses.replace(hackathon, url=target)
                target_fields = _extract_all(target_html, hackathon, gemini_api_key)
                # The wrapper still owns the authoritative dates; let the real
                # page fill everything it actually found on top of them.
                fields = {**fields, **{k: v for k, v in target_fields.items() if v}}

    if not fields:
        return hackathon

    updates: dict = {}
    if not hackathon.description and fields.get("description"):
        updates["description"] = fields["description"]
    if not hackathon.prize_text and fields.get("prize_text"):
        updates["prize_text"] = fields["prize_text"]
    if not hackathon.eligibility and fields.get("eligibility"):
        updates["eligibility"] = fields["eligibility"]
    if hackathon.is_online is None and fields.get("is_online") is not None:
        updates["is_online"] = fields["is_online"]
    if not hackathon.location and fields.get("location"):
        updates["location"] = fields["location"]
    if not hackathon.starts_at and fields.get("starts_at"):
        updates["starts_at"] = fields["starts_at"]
    if not hackathon.ends_at and fields.get("ends_at"):
        updates["ends_at"] = fields["ends_at"]
    if not hackathon.links and fields.get("links"):
        updates["links"] = fields["links"]

    return dataclasses.replace(hackathon, **updates) if updates else hackathon
