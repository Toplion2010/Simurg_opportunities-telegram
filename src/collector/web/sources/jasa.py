"""Jasa Project (jasa.dev) — a Kazakhstan / Central Asia youth catalog.

robots.txt allows /opportunities for every crawler. The site is a React SPA on
Supabase, so the HTML carries no listing data. We read what every anonymous
visitor's browser reads: the public `list-opportunities` edge function, called
with the anon key the site ships in its own JS bundle. The Supabase URL and key
are lifted from the current bundle on every run instead of being hardcoded, so
a key rotation or project move follows the site automatically.

One request gives every row, so discover() caches them and fetch() only maps.
The function takes no paging parameters and returns at most 500 rows, oldest
first (observed 2026-10-06: count=500, the site's newest card is the last
row). If it ever truncates from the new end, the log line `jasa_capped` is the
signal.

The catalog is Russian-first: `title_en` and friends exist in the schema but
were empty on every row when this was written, so every text field falls back
ru -> en -> kz. Types, formats and payment labels are Russian enums and are
translated here into the English terms the rest of the web pipeline reads.

`category_scope: Internal` rows are Jasa's own in-platform postings (their
content-manager internship, etc.) with no external destination, and are
skipped.
"""
import re
from datetime import date

from src.collector.web.base import WebItem, WebSource
from src.core.geo import is_kazakhstan
from src.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://jasa.dev"
LISTING_URL = f"{BASE_URL}/opportunities"
PAGE_URL = f"{BASE_URL}/opportunities/{{slug}}"
FUNCTION_PATH = "/functions/v1/list-opportunities"
ROW_CAP = 500

_BUNDLE_RE = re.compile(r'src="(/assets/index-[A-Za-z0-9_-]+\.js)"')
_SUPABASE_URL_RE = re.compile(r"https://[a-z0-9]+\.supabase\.co")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

_DESCRIPTION_CHARS = 1500

# The site's own filter (deadlineUtils Mn): blank status counts as visible.
_VISIBLE_STATUSES = {"", "approved", "published", "active"}

# opportunity_type -> the English taxonomy term classify.py maps to a Category.
# Unmapped types (Курс, Проект, ...) pass through as-is and fall to the title
# rules there.
_TYPES = {
    "программа": "Program",
    "конкурс": "Competition",
    "fellowship": "Fellowship",
    "стажировка": "Internship",
    "форум": "Conference",
    "конференция": "Conference",
    "грант": "Grant",
    "исследование": "Research",
    "хакатон": "Hackathon",
    "олимпиада": "Olympiad",
    "волонтёрство": "Volunteer Opportunity",
    "волонтерство": "Volunteer Opportunity",
    "курс": "Course",
    "акселератор": "Accelerator",
    "инкубатор": "Incubator",
    "стартап": "Startup",
    "буткемп": "Program",
    "pre-college": "Program",
    "подработка": "Job",
    "проект": "Project",
}

# format -> is_online. Hybrid counts as online, as ZhasLink's "online +
# offline" does: a student can take part without travelling.
_FORMATS = {
    "онлайн": True,
    "удалённо": True,
    "удаленно": True,
    "гибрид": True,
    "офлайн": False,
}

# payment_type -> (cost_amount_usd, English label). Only full funding is a
# known zero cost to the participant; "unpaid" describes an internship's
# salary, not a fee, so it stays unknown.
_PAYMENT = {
    "полное финансирование": (0.0, "Fully funded"),
    "частичное финансирование": (None, "Partially funded"),
    "денежный приз": (None, "Cash prize"),
    "стипендия": (None, "Stipend"),
    "оплачиваемая": (None, "Paid position"),
    "неоплачиваемая": (None, "Unpaid"),
    "самофинансирование": (None, "Self-funded"),
    "за свой счёт": (None, "Self-funded"),
    "за свой счет": (None, "Self-funded"),
    "доля в компании": (None, "Equity"),
}

_EDUCATION = {
    "school_7_9": "Grades 7-9",
    "school_9_12": "Grades 9-12",
    "gap_year": "Gap year",
    "bachelor": "Bachelor's",
    "master": "Master's",
    "phd": "PhD",
    "graduate": "Graduates",
}

_COUNTRY_ONLINE = {"онлайн", "online"}
# Country values that name no place. Not evidence of online either.
_NOT_A_PLACE = {"global", "international", "worldwide", "весь мир", "международный"}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11,
    "декабр": 12,
}
_ISO_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
_DAY_MONTH_YEAR_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-zа-яё]+)\.?\s+(\d{4})", re.IGNORECASE)
_MONTH_DAY_YEAR_RE = re.compile(r"([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)


def _text(row: dict, key: str) -> str | None:
    """The first non-blank of key, key_en, key_kz (Russian is the base column)."""
    for suffix in ("", "_en", "_kz"):
        value = row.get(key + suffix)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _month(word: str) -> int | None:
    word = word.lower()
    if word in _MONTHS:
        return _MONTHS[word]
    # Russian inflects month names ("мая", "июля"); match on the stem. Longest
    # stem first so "ма" (май/мая) cannot shadow "март".
    for stem in sorted(_MONTHS, key=len, reverse=True):
        if not stem.isascii() and word.startswith(stem):
            return _MONTHS[stem]
    return None


def parse_date(raw: str | None) -> date | None:
    """ISO "2026-03-31", "15 August 2026" / "15 мая 2026", or "October 8,
    2026" — the shapes the free-text deadline column actually holds. Anything
    else (including month-only "November, 2026") is None, which callers treat
    as unknown, never as closed."""
    if not raw:
        return None
    match = _ISO_RE.match(raw)
    if match:
        try:
            return date(*(int(g) for g in match.groups()))
        except ValueError:
            return None
    match = _DAY_MONTH_YEAR_RE.search(raw)
    if match:
        month = _month(match.group(2))
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                return None
    match = _MONTH_DAY_YEAR_RE.search(raw)
    if match:
        month = _month(match.group(1))
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(2)))
            except ValueError:
                return None
    return None


def _is_rolling(row: dict) -> bool:
    return str(row.get("is_rolling") or "").strip().lower() == "true"


def _is_stale(row: dict, today: date) -> bool:
    """True when the deadline (or, lacking one, the end date) is behind us.

    Rolling rows are never stale, and an unparseable or missing date stays in:
    unknown is not closed.
    """
    if _is_rolling(row):
        return False
    deadline = parse_date(row.get("application_deadline"))
    if deadline is not None:
        return deadline < today
    end = parse_date(row.get("end_date"))
    return end is not None and end < today


def _deadline(row: dict) -> str | None:
    raw = (row.get("application_deadline") or "").strip()
    parsed = parse_date(raw)
    if parsed is not None:
        return parsed.isoformat()
    if raw:
        return raw
    return "Rolling applications" if _is_rolling(row) else None


def _url(raw: str | None) -> str | None:
    """Official links are sometimes stored without a scheme ("forms.gle/...")."""
    value = (raw or "").strip()
    if not value or " " in value:
        return None
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value.lstrip("/")
    return value


def _location(row: dict) -> tuple[bool | None, str | None]:
    """(is_online, location text). A Kazakh city keeps its city name, which is
    what geo.match_kazakhstan and the card both want."""
    is_online = _FORMATS.get((row.get("format") or "").strip().lower())
    city = (row.get("city") or "").strip()
    country = (row.get("country") or "").strip()
    if country.lower() in _COUNTRY_ONLINE:
        if is_online is None:
            is_online = True
        country = ""
    elif country.lower() in _NOT_A_PLACE:
        country = ""
    if city and country and city.lower() != country.lower():
        where = f"{city}, {country}"
    else:
        where = city or country or None
    if where and is_kazakhstan(city) and not is_kazakhstan(country):
        where = f"{where}, Kazakhstan"
    return is_online, where


def _grades(raw: str | None) -> list[str]:
    labels = []
    for code in (raw or "").split(","):
        code = code.strip().lower()
        if code:
            labels.append(_EDUCATION.get(code, code))
    return labels


def _eligibility(row: dict) -> str | None:
    parts = [_text(row, "requirements")]
    lo = str(row.get("target_age_min") or "").strip()
    hi = str(row.get("target_age_max") or "").strip()
    if lo.isdigit() and hi.isdigit():
        parts.append(f"Age {lo}-{hi}.")
    elif lo.isdigit():
        parts.append(f"Age {lo}+.")
    elif hi.isdigit():
        parts.append(f"Up to age {hi}.")
    text = " ".join(p for p in parts if p)
    return text or None


def _description(row: dict) -> str | None:
    text = _text(row, "about_description")
    gain = _text(row, "what_you_gain")
    if gain:
        text = f"{text} {gain}" if text else gain
    if text and len(text) > _DESCRIPTION_CHARS:
        text = text[:_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
    return text


class JasaSource(WebSource):
    name = "jasa"

    def __init__(self, fetcher) -> None:
        self._fetcher = fetcher
        self._rows: dict[str, dict] = {}

    # ---------------------------------------------------------------- discover

    def discover(self) -> list[str]:
        self._rows = {}
        credentials = self._credentials()
        if credentials is None:
            return []
        api_url, key = credentials

        try:
            response = self._fetcher.get(
                api_url + FUNCTION_PATH,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            payload = response.json()
        except Exception:
            logger.exception("jasa_api_failed")
            return []
        rows = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            logger.warning("jasa_unexpected_payload")
            return []
        if len(rows) >= ROW_CAP:
            logger.warning("jasa_capped", rows=len(rows))

        today = date.today()
        stale = skipped = 0
        # Oldest first on the wire; walk newest first so a duplicated slug
        # keeps its newest row and the collector's per-run cap takes new ones.
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            slug = (row.get("slug") or "").strip()
            if (
                not slug
                or slug in self._rows
                or (row.get("status") or "").strip().lower() not in _VISIBLE_STATUSES
                or (row.get("category_scope") or "").strip().lower() == "internal"
            ):
                skipped += 1
                continue
            if _is_stale(row, today):
                stale += 1
                continue
            self._rows[slug] = row

        logger.info(
            "jasa_discovered",
            rows=len(rows),
            stale=stale,
            skipped=skipped,
            live=len(self._rows),
        )
        return list(self._rows)

    def _credentials(self) -> tuple[str, str] | None:
        """(supabase_url, anon_key) from the site's current JS bundle."""
        try:
            page = self._fetcher.get(LISTING_URL).text
            bundle_path = _BUNDLE_RE.search(page)
            if not bundle_path:
                logger.warning("jasa_no_bundle")
                return None
            bundle = self._fetcher.get(BASE_URL + bundle_path.group(1)).text
        except Exception:
            logger.exception("jasa_bundle_failed")
            return None

        url = _SUPABASE_URL_RE.search(bundle)
        key = _JWT_RE.search(bundle)
        if not url or not key:
            logger.warning("jasa_no_credentials", url=bool(url), key=bool(key))
            return None
        return url.group(0), key.group(0)

    # ------------------------------------------------------------------- fetch

    def fetch(self, external_ids: list[str]) -> list[WebItem]:
        if external_ids and not self._rows:
            self.discover()
        items: list[WebItem] = []
        for slug in external_ids:
            row = self._rows.get(slug)
            if row is None:
                continue
            try:
                item = self._build(slug, row)
            except Exception:
                logger.exception("jasa_item_failed", slug=slug)
                continue
            if item is not None:
                items.append(item)
        return items

    def _build(self, slug: str, row: dict) -> WebItem | None:
        title = _text(row, "title")
        if not title:
            return None

        payment = (row.get("payment_type") or "").strip()
        cost_amount, cost_text = _PAYMENT.get(payment.lower(), (None, payment or None))
        is_online, where = _location(row)
        raw_type = (row.get("opportunity_type") or "").strip()
        subjects = [_TYPES.get(raw_type.lower(), raw_type)] if raw_type else []

        return WebItem(
            source=self.name,
            external_id=slug,
            title=title,
            page_url=PAGE_URL.format(slug=slug),
            apply_url=_url(row.get("official_website")),
            description=_description(row),
            organizer=(row.get("organizer_name") or "").strip() or None,
            deadline=_deadline(row),
            starts_at=(row.get("start_date") or "").strip() or None,
            cost_amount=cost_amount,
            cost_currency=None,
            cost_text=cost_text,
            eligibility=_eligibility(row),
            duration=(row.get("duration") or "").strip() or None,
            country=where,
            is_online=is_online,
            grades=_grades(row.get("education_level")),
            subjects=subjects,
            raw={
                "skills_tags": row.get("skills_tags") or "",
                "end_date": row.get("end_date") or "",
                "is_rolling": _is_rolling(row),
            },
        )
