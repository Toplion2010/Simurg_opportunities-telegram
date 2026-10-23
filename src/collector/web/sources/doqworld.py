"""doq.world competition listings, collected under written permission.

Authorization is recorded in ``docs/permissions/doq-world.md``. Discovery uses
the public sitemap and only follows ``/competitions/<slug>`` entries. Detail
pages are server-rendered, so this parser reads the visible competition text;
it deliberately ignores JSON-LD, navigation, prestige commentary, and hidden
application data. Only organizer/registration anchors visibly contained in the
competition content can become published links.

The sitemap had no ``lastmod`` values when checked on 2026-09-29. Consequently
it can identify new slugs without touching known pages, but cannot cheaply
detect edits. Fetching every known page to look for changes would conflict with
the low-load condition, so the collector stays new-slug-only until doq.world
adds a revision signal.
"""
import html
import re
from datetime import date, datetime
from urllib.parse import urlparse

from src.collector.web.base import WebItem, WebSource
from src.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://doq.world"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
ITEM_URL = f"{BASE_URL}/competitions/{{slug}}"

_LOC_RE = re.compile(r"<loc>\s*https://doq\.world/competitions/([^<\s/]+)/*\s*</loc>", re.I)
_MAIN_RE = re.compile(r"<main\b[^>]*>(.*?)</main>", re.S | re.I)
_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)
_DESCRIPTION_RE = re.compile(r'<p\b[^>]*class="[^"]*\bmax-w-xl\b[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
_ORGANIZER_RE = re.compile(
    r"Organized by(?:<!--.*?-->)?\s*<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
    re.S | re.I,
)
_ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_FACT_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\bneu-inset\b[^"]*"[^>]*>\s*'
    r'<div\b[^>]*class="[^"]*text-muted-foreground[^"]*"[^>]*>'
    r'((?:(?!<div\b).)*)</div>\s*'
    r'<div\b[^>]*class="[^"]*font-semibold[^"]*"[^>]*>'
    r'((?:(?!<div\b).)*)</div>\s*</div>',
    re.S | re.I,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_USD_RE = re.compile(r"(?:US\s*)?\$\s*(\d[\d,]*(?:\.\d+)?)", re.I)
_DATE_RE = re.compile(r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\b")
_EDITORIAL_SENTENCE_RE = re.compile(
    r"\b(?:one of the (?:most )?prestigious|"
    r"(?:is|are|makes? (?:it|this))\s+(?:a|the)\s+"
    r"(?:top|strong|ideal|excellent|great|prestigious|compelling))\b",
    re.I,
)
_ORGANIZER_MARKETING_RE = re.compile(
    r",?\s*described by organizers as [^.!?]+",
    re.I,
)

_EMPTY = {"", "loading...", "not disclosed", "unknown", "n/a", "tbd", "tba", "—", "-"}
_MAPPED_FACTS = {
    "time commitment",
    "eligibility",
    "location",
    "field",
    "format",
    "age",
    "registration fee",
    "deadline",
    "prize",
}


def _text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    value = _SCRIPT_STYLE_RE.sub(" ", fragment)
    value = html.unescape(_TAG_RE.sub(" ", value))
    value = " ".join(value.split())
    return value or None


def _facts(main: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_label, raw_value in _FACT_RE.findall(main):
        label = _text(raw_label)
        value = _text(raw_value)
        if not label or not value or value.lower() in _EMPTY:
            continue
        result[label.lower()] = value
    return result


def _cost(raw: str | None) -> tuple[float | None, str | None, str | None]:
    if not raw:
        return None, None, None
    if raw.strip().lower() == "free":
        return 0.0, None, "Free"
    match = _USD_RE.search(raw)
    if match:
        return float(match.group(1).replace(",", "")), "USD", raw
    return None, None, raw


def _attendance(raw: str | None) -> bool | None:
    value = (raw or "").strip().lower()
    if value in {"online", "virtual", "remote", "hybrid"}:
        return True
    if value in {"in-person", "in person", "onsite", "on-site"}:
        return False
    return None


def _deadline_passed(raw: str | None, today: date | None = None) -> bool:
    """Whether a stated English deadline date is strictly before today."""
    match = _DATE_RE.search(raw or "")
    if not match:
        return False
    try:
        deadline = datetime.strptime(match.group(1), "%b %d, %Y").date()
    except ValueError:
        try:
            deadline = datetime.strptime(match.group(1), "%B %d, %Y").date()
        except ValueError:
            return False
    return deadline < (today or date.today())


def _description(fragment: str | None) -> str | None:
    """Visible lead summary with subjective editorial sentences removed."""
    value = _text(fragment)
    if not value:
        return None
    value = _ORGANIZER_MARKETING_RE.sub("", value)
    sentences = re.findall(r"[^.!?]+(?:[.!?]+|$)", value)
    kept = [sentence.strip() for sentence in sentences if not _EDITORIAL_SENTENCE_RE.search(sentence)]
    return " ".join(kept) or None


def _visible_links(main: str, organizer_href: str | None) -> tuple[list[str], list[dict[str, str]]]:
    """Eligible external URLs and the exact visible fragments that exposed them."""
    urls: list[str] = []
    provenance: list[dict[str, str]] = []
    for raw_url, raw_label in _ANCHOR_RE.findall(main):
        url = html.unescape(raw_url).strip()
        label = _text(raw_label)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if parsed.netloc.lower() in {"doq.world", "www.doq.world"}:
            continue

        # An organizer-name anchor is explicitly part of the opportunity text.
        # Otherwise require the page to visibly print a hostname; generic
        # buttons such as "Apply" are intentionally not enough.
        is_organizer = organizer_href is not None and url == organizer_href
        prints_host = bool(label and "." in label and parsed.netloc.split(":", 1)[0] in label)
        if not is_organizer and not prints_host:
            continue

        fragment = f"Organized by {label}" if is_organizer else (label or url)
        provenance.append({"url": url, "text": fragment})
        if url not in urls:
            urls.append(url)
    return urls, provenance


class DoqWorldSource(WebSource):
    name = "doqworld"

    def __init__(self, fetcher) -> None:
        self._fetcher = fetcher

    def discover(self) -> list[str]:
        try:
            sitemap = self._fetcher.get(SITEMAP_URL).text
        except Exception:
            logger.exception("doqworld_sitemap_failed")
            return []

        slugs = list(dict.fromkeys(html.unescape(slug) for slug in _LOC_RE.findall(sitemap)))
        logger.info("doqworld_discovered", count=len(slugs), has_lastmod="<lastmod>" in sitemap)
        return slugs

    def fetch(self, external_ids: list[str]) -> list[WebItem]:
        items: list[WebItem] = []
        for slug in external_ids:
            try:
                item = self._fetch_one(slug)
            except Exception:
                logger.exception("doqworld_item_failed", slug=slug)
                continue
            if item is not None:
                items.append(item)
        return items

    def _fetch_one(self, slug: str) -> WebItem | None:
        page_url = ITEM_URL.format(slug=slug)
        page = self._fetcher.get(page_url).text
        main_match = _MAIN_RE.search(page)
        if not main_match:
            logger.warning("doqworld_no_main", slug=slug)
            return None
        main = main_match.group(1)

        title_match = _H1_RE.search(main)
        title = _text(title_match.group(1)) if title_match else None
        if not title:
            logger.warning("doqworld_no_title", slug=slug)
            return None

        description_match = _DESCRIPTION_RE.search(main)
        description = _description(description_match.group(1)) if description_match else None

        organizer_match = _ORGANIZER_RE.search(main)
        organizer_href = html.unescape(organizer_match.group(1)) if organizer_match else None
        organizer = _text(organizer_match.group(2)) if organizer_match else None

        facts = _facts(main)
        links, link_provenance = _visible_links(main, organizer_href)
        cost_amount, cost_currency, cost_text = _cost(facts.get("registration fee"))

        eligibility = facts.get("eligibility")
        if not eligibility and facts.get("age"):
            eligibility = f"Ages {facts['age']}"

        notes = [
            f"{label.title()}: {value}"
            for label, value in facts.items()
            if label not in _MAPPED_FACTS
        ]
        extra_notes = ". ".join(notes) or None

        text_lines = [title]
        if organizer:
            text_lines.append(f"Organized by {organizer}")
        if description:
            text_lines.append(description)
        text_lines.extend(f"{label.title()}: {value}" for label, value in facts.items())
        for entry in link_provenance:
            text_lines.append(f"Link ({entry['text']}): {entry['url']}")
        opportunity_text = "\n".join(text_lines)

        # Let specific title words (Olympiad, Conference, Hackathon, ...) win.
        # The source path itself is not a taxonomy precise enough to flatten
        # every doq.world listing into the generic Competition category.
        subjects = [facts.get("field")]
        deadline = facts.get("deadline")
        return WebItem(
            source=self.name,
            external_id=slug,
            title=title,
            page_url=page_url,
            apply_url=links[0] if links else None,
            additional_urls=links[1:],
            description=description,
            organizer=organizer,
            deadline=deadline,
            cost_amount=cost_amount,
            cost_currency=cost_currency,
            cost_text=cost_text,
            eligibility=eligibility,
            duration=facts.get("time commitment"),
            country=facts.get("location"),
            is_online=_attendance(facts.get("format")),
            subjects=[value for value in subjects if value],
            rewards=facts.get("prize"),
            extra_notes=extra_notes,
            source_excerpt=opportunity_text,
            raw={
                "facts": facts,
                "opportunity_text": opportunity_text,
                "link_provenance": link_provenance,
                "is_closed": _deadline_passed(deadline),
            },
        )
