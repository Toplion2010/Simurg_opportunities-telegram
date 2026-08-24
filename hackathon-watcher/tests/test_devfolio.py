from __future__ import annotations

from datetime import date

from sources.base import Hackathon
from sources.devfolio import DevfolioSource


def test_devfolio_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("devfolio.html")
    monkeypatch.setattr("sources.devfolio.get", lambda *a, **k: response)

    hackathons = DevfolioSource().fetch()

    assert len(hackathons) == 2
    offline, online = hackathons

    assert offline.title == "Test Hack Season 2"
    assert offline.url == "https://test-hack-season-2.devfolio.co/"
    assert offline.source_id == offline.url
    assert offline.is_online is False
    assert offline.starts_at == date(2026, 9, 25)
    assert offline.themes == ["No Restrictions"]

    assert online.title == "Test Online Hack"
    assert online.is_online is True
    assert online.themes == ["Blockchain", "AI"]


def test_devfolio_returns_empty_when_data_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.devfolio.get", lambda *a, **k: FakeResponse("<html></html>"))
    assert DevfolioSource().fetch() == []


def _bare_hackathon() -> Hackathon:
    return Hackathon(
        source="devfolio", source_id="1", title="Test Hack",
        url="https://dothack26.devfolio.co/", starts_at=date(2026, 9, 4),
        ends_at=date(2026, 9, 6), is_online=False, prize_text=None,
        location=None, themes=[], raw={},
    )


def test_devfolio_enrich_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("devfolio_detail.html")
    monkeypatch.setattr("sources.devfolio.get", lambda *a, **k: response)

    enriched = DevfolioSource().enrich(_bare_hackathon())

    assert enriched.prize_text == "USD 1,050.46"
    assert enriched.description
    assert "hack '26" in enriched.description.lower()
    assert "**" not in enriched.description
    assert enriched.sponsors == ["Acme Corp", "TechCo"]
    # listing-level fields must be untouched
    assert enriched.title == "Test Hack"


def test_devfolio_enrich_returns_unchanged_when_next_data_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.devfolio.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    original = _bare_hackathon()

    enriched = DevfolioSource().enrich(original)
    assert enriched == original


def test_devfolio_enrich_returns_unchanged_on_fetch_failure(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.devfolio.get", _raise)
    original = _bare_hackathon()

    enriched = DevfolioSource().enrich(original)
    assert enriched == original
