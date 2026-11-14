"""Jasa scraper, against nine real rows of its `list-opportunities` function.

No network. The cases that matter: credentials are lifted from the site's own
bundle (and a missing bundle degrades to empty, never raises), the free-text
deadline column is read in both its ISO and "15 Май 2026" shapes, rolling and
unparseable deadlines stay in, Jasa's own internal postings stay out, and the
Russian enums reach the pipeline as the English terms it reads.
"""
import json
import pathlib
from datetime import date

import pytest

from src.collector.web.classify import category_from
from src.collector.web.filters import admits
from src.core.enums import Category
from src.collector.web.sources import jasa
from src.collector.web.sources.jasa import JasaSource, _is_stale, _url, parse_date

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "web"

API = "https://abcdefgh.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.c2lnbmF0dXJl"
LISTING = '<html><script type="module" src="/assets/index-AbC123.js"></script></html>'
BUNDLE = f'const u="{API}",k="{KEY}";createClient(u,k)'

ESSAY = "global-essay-prize-2026-john-locke"  # ISO deadline 2026-03-31
ABC = "abc-weekend-nuris"  # Astana, deadline 2026-02-28, schemeless link
JASA_PM = "jasa-platform-content-manager-internship-2026"  # Internal
JASA_CM = "jasa-content-creator-internship-2026"  # Internal
SHIFTERS = "social-shifters-global-innovation-challenge-2026"  # "31 August 2026"
CAMBRIDGE = "cambridge-future-scholar-program"  # "15 Май 2026", rolling
CONSULATE = "us-consulate-almaty-protocol-internship-2026"  # "22 June 2026"
SCOUT = "scout-adventures-volunteer-uk-2026"  # "открыто", fully funded
VTSP = "venture-tech-summer-program-vtsp"  # 2026-03-28, end_date in August


def _rows() -> list[dict]:
    return json.loads((FIXTURES / "jasa_opportunities.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, text: str = "", payload=None) -> None:
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeFetcher:
    def __init__(self, rows=None, listing: str = LISTING, bundle: str = BUNDLE) -> None:
        self.rows = _rows() if rows is None else rows
        self.listing = listing
        self.bundle = bundle
        self.api_calls: list[dict] = []

    def get(self, url, **kwargs):
        if url == jasa.LISTING_URL:
            return FakeResponse(self.listing)
        if url.endswith("/assets/index-AbC123.js"):
            return FakeResponse(self.bundle)
        if url == API + jasa.FUNCTION_PATH:
            self.api_calls.append(kwargs)
            return FakeResponse(
                payload={"items": self.rows, "count": len(self.rows), "version": "x"}
            )
        raise AssertionError(f"unexpected GET: {url}")


@pytest.fixture
def june_first(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 6, 1)

    monkeypatch.setattr(jasa, "date", FixedDate)


def test_credentials_come_from_the_bundle(june_first):
    fetcher = FakeFetcher()
    JasaSource(fetcher).discover()
    (call,) = fetcher.api_calls
    assert call["headers"] == {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def test_discover_drops_closed_and_internal_newest_first(june_first):
    ids = JasaSource(FakeFetcher()).discover()
    # Closed by deadline -- VTSP's later end_date does not reopen it.
    assert not {ESSAY, ABC, VTSP} & set(ids)
    # Jasa's own in-platform postings.
    assert not {JASA_PM, JASA_CM} & set(ids)
    # Rolling, a future text deadline, and an unparseable one ("открыто").
    assert ids == [SCOUT, CONSULATE, CAMBRIDGE, SHIFTERS]


def test_duplicate_slug_keeps_newest_row(june_first):
    rows = _rows()
    older = dict(next(r for r in rows if r["slug"] == SHIFTERS), title="Old copy")
    source = JasaSource(FakeFetcher(rows=[older] + rows))
    source.discover()
    (item,) = source.fetch([SHIFTERS])
    assert item.title == "Social Shifters Global Innovation Challenge 2026"


def test_parse_date_shapes():
    assert parse_date("2026-03-31") == date(2026, 3, 31)
    assert parse_date("31 August 2026") == date(2026, 8, 31)
    assert parse_date(" 2 August 2026") == date(2026, 8, 2)
    assert parse_date("15 Май 2026") == date(2026, 5, 15)
    assert parse_date("15 мая 2026") == date(2026, 5, 15)
    assert parse_date("3 марта 2026") == date(2026, 3, 3)
    assert parse_date("19 August 2026 (Doctoral tracks; other tracks rolling)") == date(
        2026, 8, 19
    )
    assert parse_date("October 8, 2026") == date(2026, 10, 8)
    assert parse_date("5th July 2026") == date(2026, 7, 5)
    for unknown in ("November, 2026", "открыто", "202-04-27", "15 july", "", None):
        assert parse_date(unknown) is None


def test_is_stale():
    today = date(2026, 6, 1)
    assert _is_stale({"application_deadline": "2026-05-31"}, today)
    assert not _is_stale({"application_deadline": "2026-05-31", "is_rolling": "true"}, today)
    assert not _is_stale({"application_deadline": "открыто"}, today)
    assert _is_stale({"application_deadline": "", "end_date": "2026-01-01"}, today)
    assert not _is_stale({}, today)


def test_item_fields(june_first):
    source = JasaSource(FakeFetcher())
    source.discover()
    items = {i.external_id: i for i in source.fetch([SHIFTERS, CAMBRIDGE, CONSULATE, SCOUT])}

    shifters = items[SHIFTERS]
    assert shifters.page_url == f"https://jasa.dev/opportunities/{SHIFTERS}"
    assert shifters.apply_url.startswith("https://www.socialshifters.co/")
    assert shifters.deadline == "2026-08-31"
    assert shifters.is_online is True
    assert shifters.cost_text == "Cash prize"
    assert shifters.cost_amount is None
    assert "Age 18-30." in shifters.eligibility
    assert "Bachelor's" in shifters.grades

    cambridge = items[CAMBRIDGE]
    assert cambridge.deadline == "2026-05-15"
    assert cambridge.is_online is True
    assert cambridge.country is None  # "Global" is not a place
    assert "Grades 9-12" in cambridge.grades
    assert "Age 16+." in cambridge.eligibility

    consulate = items[CONSULATE]
    assert consulate.is_online is False
    assert consulate.country == "Almaty, Kazakhstan"
    assert consulate.subjects == ["Internship"]
    assert category_from(consulate) == Category.Internship

    scout = items[SCOUT]
    assert scout.deadline == "открыто"
    assert scout.cost_amount == 0.0
    assert scout.cost_text == "Fully funded"
    assert category_from(scout) == Category.Volunteer
    # In person abroad, but costs the participant nothing.
    assert admits(scout) == (True, "admitted")


def test_url_normalization():
    assert _url("forms.gle/abc") == "https://forms.gle/abc"
    assert _url("https://x.org/a") == "https://x.org/a"
    assert _url("") is None
    assert _url("see website") is None


@pytest.mark.parametrize(
    "listing,bundle",
    [
        ("<html>redesigned, no module script</html>", BUNDLE),
        (LISTING, "bundle with no supabase config"),
    ],
)
def test_markup_change_degrades_to_empty(listing, bundle):
    assert JasaSource(FakeFetcher(listing=listing, bundle=bundle)).discover() == []


def test_network_failure_never_raises():
    class Broken:
        def get(self, url, **kwargs):
            raise ConnectionError("down")

    source = JasaSource(Broken())
    assert source.discover() == []
    assert source.fetch([SHIFTERS]) == []
