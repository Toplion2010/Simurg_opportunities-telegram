from __future__ import annotations

from datetime import date

from sources.reskilll import ReskilllSource


def test_reskilll_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("reskilll.html")
    monkeypatch.setattr("sources.reskilll.get", lambda *a, **k: response)

    hackathons = ReskilllSource().fetch()

    assert len(hackathons) == 2
    online, offline = hackathons

    assert online.title == "Test Online Hackathon"
    assert online.url == "https://testonline.reskilll.com/"
    assert online.is_online is True
    assert online.starts_at == date(2026, 9, 20)
    assert online.ends_at == date(2026, 9, 21)
    assert "AI" in online.themes

    assert offline.title == "Test Onsite Hackathon"
    assert offline.is_online is False
    assert offline.location == "Delhi NCR"
    assert offline.starts_at == date(2026, 10, 5)


def test_reskilll_returns_empty_when_cards_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.reskilll.get", lambda *a, **k: FakeResponse("<html><body>nope</body></html>"))
    assert ReskilllSource().fetch() == []
