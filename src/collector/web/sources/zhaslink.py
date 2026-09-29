"""ZhasLink (zhaslink.invisionu.education) — a Kazakhstan-focused youth catalog.

Runs WITHOUT the site's permission, by the owner's explicit decision. ZhasLink's
Terms prohibit "using automated means to collect data from the Platform without
our prior written consent". They also run a key-gated partner API
(functions/v1/api-gateway/api-opportunities, header X-API-Key, keys issued via
zhaslink@invisionu.education). If a key is ever obtained, switch this source to
that API. To turn the source off without a deploy, deactivate its
source_channels row.

The site is a React SPA on Supabase, so the HTML carries no listing data. We
read what every anonymous visitor's browser reads: the public `opportunities`
table through Supabase's REST endpoint, with the anon key the site ships in its
own JS bundle. No login, and only the non-archived rows the public listing
shows. The Supabase URL and key are lifted from the current bundle on every
run instead of being hardcoded, so a key rotation or project move follows the
site automatically. Columns are selected explicitly, which keeps `created_by`
(their user ids) and the rest of their admin fields out of our database.

One request gives every row, so discover() caches them and fetch() only maps.
"""
import re
from datetime import date

from src.collector.web.base import WebItem, WebSource
from src.core.geo import is_kazakhstan
from src.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://zhaslink.invisionu.education"
LISTING_URL = f"{BASE_URL}/en/opportunities"
PAGE_URL = f"{BASE_URL}/en/opportunities/{{slug}}"

COLUMNS = (
    "id,title_en,title_ru,title_kz,description_en,description_ru,"
    "requirements_en,requirements_ru,content_en,organizer,region,cost,level,"
    "grade,tags,opportunity_type,subject_area,application_url,source_url,"
    "start_date,end_date,application_end_date,event_date,created_at"
)
PAGE_SIZE = 500
# ~21 live rows today. Headroom, not an expected page count.
MAX_PAGES = 10

_BUNDLE_RE = re.compile(r'src="(/assets/index-[A-Za-z0-9_-]+\.js)"')
_SUPABASE_URL_RE = re.compile(r"https://[a-z0-9]+\.supabase\.co")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

_LEADING_SYMBOLS_RE = re.compile(r"^[^\w(\"'«]+", re.UNICODE)
_MARKDOWN_RE = re.compile(r"\*\*|__|\[([^\]]*)\]\([^)]*\)")
_SLUG_DROP_RE = re.compile(r"[^a-z0-9\s-]")
_SLUG_SEP_RE = re.compile(r"[\s_-]+")
_USD_RE = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")

_DESCRIPTION_CHARS = 1500
_ONLINE_REGIONS = {"online": True, "online + offline": True}


def _clean_title(title: str | None) -> str | None:
    """Drop the decorative emoji most titles open with — "🔧 Engineering Camp"."""
    if not title:
        return None
    value = _LEADING_SYMBOLS_RE.sub("", title).strip()
    return value or title.strip() or None


def _markdown_to_text(value: str | None) -> str | None:
    if not value:
        return None
    value = _MARKDOWN_RE.sub(lambda m: m.group(1) or "", value)
    value = " ".join(value.split())
    return value or None


def _slug(title: str | None, row_id: str) -> str:
    """The site's own URL shape: slugified English title (60 chars) + first 8
    chars of the id. The id prefix alone also resolves, which is the fallback
    for titles with no Latin letters."""
    short_id = row_id[:8]
    text = _SLUG_DROP_RE.sub("", (title or "").lower())
    text = _SLUG_SEP_RE.sub("-", text).strip("-")[:60].strip("-")
    return f"{text}-{short_id}" if text else short_id


def _description(row: dict) -> str | None:
    """Paragraph blocks of the rich content, else the plain description."""
    paragraphs = [
        block.get("content")
        for block in row.get("content_en") or []
        if isinstance(block, dict) and block.get("type") == "paragraph"
    ]
    text = _markdown_to_text(" ".join(p for p in paragraphs if isinstance(p, str)))
    if not text:
        text = _markdown_to_text(row.get("description_en") or row.get("description_ru"))
    if text and len(text) > _DESCRIPTION_CHARS:
        text = text[:_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
    return text


def _cost(raw: str | None) -> tuple[float | None, str | None, str | None]:
    """(amount_usd, currency, text). "paid" with no number is UNKNOWN, and a
    tenge amount stays text-only: the admission filter compares cost_amount to
    a USD threshold, so passing 10,000 KZT through as 10000 would reject a
    ~$20 course as expensive."""
    if not raw or not raw.strip():
        return None, None, None
    text = raw.strip()
    lowered = text.lower()
    if lowered == "free":
        return 0.0, None, "Free"
    if lowered == "paid":
        return None, None, "Paid"
    match = _USD_RE.search(text)
    if match:
        return float(match.group(1).replace(",", "")), "USD", text
    return None, None, text


def _is_stale(row: dict, today: date) -> bool:
    """True when the listing's last known date is already behind us.

    ZhasLink leaves finished events un-archived (observed: a March camp still
    listed in September), and application_end_date is almost never filled in.
    So the latest of the three end-ish dates decides; a row with none of them
    stays in, since unknown is not closed. start_date alone is not proof — an
    ongoing course started months ago can still be open.
    """
    ends = []
    for key in ("application_end_date", "end_date", "event_date"):
        value = row.get(key)
        if not value:
            continue
        try:
            ends.append(date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue
    return bool(ends) and max(ends) < today


def _grades(raw: list | None) -> list[str]:
    """"9" -> "Grade 9", so to_dto's audience hints (which want "grade 9", not
    a bare digit) can read them; "University" passes through."""
    labels = []
    for value in raw or []:
        value = str(value).strip()
        if not value:
            continue
        labels.append(f"Grade {value}" if value.isdigit() else value)
    return labels


def _location(region: str | None) -> tuple[bool | None, str | None]:
    """(is_online, country-ish location). Kazakh cities keep the city name,
    which is what geo.match_kazakhstan and the card both want."""
    region = (region or "").strip()
    if not region:
        return None, None
    online = _ONLINE_REGIONS.get(region.lower())
    if online is not None:
        return online, None
    if is_kazakhstan(region) and "kazakhstan" not in region.lower():
        return False, f"{region}, Kazakhstan"
    return False, region


class ZhasLinkSource(WebSource):
    name = "zhaslink"

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

        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            try:
                response = self._fetcher.get(
                    f"{api_url}/rest/v1/opportunities",
                    params={
                        "select": COLUMNS,
                        "archived": "eq.false",
                        "order": "created_at.desc",
                        "limit": str(PAGE_SIZE),
                        "offset": str(page * PAGE_SIZE),
                    },
                    headers=headers,
                )
                batch = response.json()
            except Exception:
                logger.exception("zhaslink_api_failed", page=page)
                break
            if not isinstance(batch, list) or not batch:
                break
            rows.extend(r for r in batch if isinstance(r, dict))
            if len(batch) < PAGE_SIZE:
                break

        today = date.today()
        stale = 0
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                continue
            if _is_stale(row, today):
                stale += 1
                continue
            self._rows[str(row_id)] = row

        logger.info(
            "zhaslink_discovered", rows=len(rows), stale=stale, live=len(self._rows)
        )
        return list(self._rows)

    def _credentials(self) -> tuple[str, str] | None:
        """(supabase_url, anon_key) from the site's current JS bundle."""
        try:
            page = self._fetcher.get(LISTING_URL).text
            bundle_path = _BUNDLE_RE.search(page)
            if not bundle_path:
                logger.warning("zhaslink_no_bundle")
                return None
            bundle = self._fetcher.get(BASE_URL + bundle_path.group(1)).text
        except Exception:
            logger.exception("zhaslink_bundle_failed")
            return None

        url = _SUPABASE_URL_RE.search(bundle)
        key = _JWT_RE.search(bundle)
        if not url or not key:
            logger.warning("zhaslink_no_credentials", url=bool(url), key=bool(key))
            return None
        return url.group(0), key.group(0)

    # ------------------------------------------------------------------- fetch

    def fetch(self, external_ids: list[str]) -> list[WebItem]:
        if external_ids and not self._rows:
            self.discover()
        items: list[WebItem] = []
        for row_id in external_ids:
            row = self._rows.get(row_id)
            if row is None:
                continue
            try:
                item = self._build(row)
            except Exception:
                logger.exception("zhaslink_item_failed", id=row_id)
                continue
            if item is not None:
                items.append(item)
        return items

    def _build(self, row: dict) -> WebItem | None:
        row_id = str(row["id"])
        title = _clean_title(row.get("title_en") or row.get("title_ru") or row.get("title_kz"))
        if not title:
            return None

        cost_amount, cost_currency, cost_text = _cost(row.get("cost"))
        is_online, country = _location(row.get("region"))
        eligibility = _markdown_to_text(
            row.get("requirements_en") or row.get("requirements_ru")
        )

        subjects = [
            value
            for value in [row.get("opportunity_type"), row.get("subject_area")]
            if value
        ]

        return WebItem(
            source=self.name,
            external_id=row_id,
            title=title,
            page_url=PAGE_URL.format(slug=_slug(row.get("title_en"), row_id)),
            apply_url=row.get("application_url") or row.get("source_url"),
            description=_description(row),
            organizer=(row.get("organizer") or "").strip() or None,
            deadline=row.get("application_end_date"),
            starts_at=row.get("start_date") or row.get("event_date"),
            cost_amount=cost_amount,
            cost_currency=cost_currency,
            cost_text=cost_text,
            eligibility=eligibility,
            country=country,
            is_online=is_online,
            grades=_grades(row.get("grade")),
            subjects=subjects,
            raw={
                "level": row.get("level"),
                "tags": row.get("tags") or [],
                "end_date": row.get("end_date"),
            },
        )
