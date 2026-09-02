"""ExtracurricularHub scraper, against a saved copy of a real detail page.

No network: the fetcher is a stub. Follows hackathon-watcher/tests' pattern —
assert the parsed values, assert graceful empty on markup change, assert
fetch() never raises.
"""
import pathlib

import pytest

from src.collector.web.sources.extracurricularhub import ExtracurricularHubSource

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "web"


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeFetcher:
    """Serves saved bodies by URL substring; raises for anything unexpected so a
    test can never silently hit the network."""

    def __init__(self, routes: dict[str, str]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for marker, body in self.routes.items():
            if marker in url:
                if isinstance(body, Exception):
                    raise body
                return FakeResponse(body)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def pumac_page() -> str:
    return (FIXTURES / "ech_pumac.html").read_text(encoding="utf-8")


@pytest.fixture
def sitemap() -> str:
    return (FIXTURES / "ech_sitemap.xml").read_text(encoding="utf-8")


def test_discover_returns_slugs(sitemap):
    source = ExtracurricularHubSource(FakeFetcher({"sitemap-opportunities": sitemap}))
    slugs = source.discover()
    assert slugs
    assert all("/" not in slug for slug in slugs)
    assert "zonta-young-women-in-leadership-award" in slugs


def test_discover_deduplicates_and_survives_failure():
    source = ExtracurricularHubSource(
        FakeFetcher({"sitemap-opportunities": RuntimeError("boom")})
    )
    assert source.discover() == []


def test_parses_the_official_apply_url(pumac_page):
    """The single most important field: apply_url must be the OFFICIAL site,
    not the catalog page. Simurg hashes title+apply_link for dedup, so pointing
    this at extracurricularhub.com would break collision with Telegram posts."""
    source = ExtracurricularHubSource(FakeFetcher({"pumac": pumac_page}))
    (item,) = source.fetch(["pumac-princeton-university-mathematics-competition"])
    assert item.apply_url == "https://pumac.princeton.edu/"
    assert "extracurricularhub.com" in item.page_url


def test_parses_structured_fields(pumac_page):
    source = ExtracurricularHubSource(FakeFetcher({"pumac": pumac_page}))
    (item,) = source.fetch(["pumac-princeton-university-mathematics-competition"])

    assert item.title == "PUMaC (Princeton University Mathematics Competition)"
    assert item.organizer == "Princeton University Mathematics Department"
    assert item.cost_amount == 12.5
    assert item.cost_currency == "USD"
    assert item.country == "US"
    assert item.starts_at == "2026-11-21"
    assert item.eligibility == "Up to age 19"
    # MixedEventAttendanceMode -> reachable online.
    assert item.is_online is True


def test_boilerplate_description_is_dropped(pumac_page):
    """ECH generates 'X is a STEM opportunity listed on ExtracurricularHub' for
    every listing. Publishing it would put another site's name in our card and
    state nothing the fields do not already carry."""
    source = ExtracurricularHubSource(FakeFetcher({"pumac": pumac_page}))
    (item,) = source.fetch(["pumac-princeton-university-mathematics-competition"])
    assert item.description is None


def test_deadline_placeholder_reads_as_unknown(pumac_page):
    """The key-facts table says 'Coming soon'. That is not a deadline, and
    startDate must never be substituted for one."""
    source = ExtracurricularHubSource(FakeFetcher({"pumac": pumac_page}))
    (item,) = source.fetch(["pumac-princeton-university-mathematics-competition"])
    assert item.deadline is None


def test_no_jsonld_yields_nothing_rather_than_raising():
    source = ExtracurricularHubSource(FakeFetcher({"anything": "<html>hi</html>"}))
    assert source.fetch(["anything"]) == []


def test_fetch_never_raises_on_network_error():
    source = ExtracurricularHubSource(FakeFetcher({"x": RuntimeError("offline")}))
    assert source.fetch(["x"]) == []


def test_one_broken_item_does_not_lose_the_others(pumac_page):
    class Flaky(FakeFetcher):
        def get(self, url, **kwargs):
            if "broken" in url:
                raise RuntimeError("500")
            return FakeResponse(pumac_page)

    source = ExtracurricularHubSource(Flaky({}))
    items = source.fetch(["broken", "pumac-ok"])
    assert len(items) == 1
