from __future__ import annotations

from datetime import date

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
