from __future__ import annotations

from datetime import date

from sources.hackathoncom import HackathonComSource, _parse_date


def test_hackathoncom_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("hackathoncom.html")
    monkeypatch.setattr("sources.hackathoncom.get", lambda *a, **k: response)

    hackathons = HackathonComSource().fetch()

    assert len(hackathons) == 3
    titles = [h.title for h in hackathons]
    assert "AI Builders Challenge with IBM Bob" in titles

    first = next(h for h in hackathons if h.title == "AI Builders Challenge with IBM Bob")
    assert first.source == "hackathoncom"
    assert first.url.startswith("https://www.hackathon.com/event/")
    assert first.is_online is True
    assert first.location is None
    assert first.ends_at is None
    assert "AI" in first.themes
    assert first.starts_at is not None


def test_hackathoncom_returns_empty_when_selectors_rot(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.hackathoncom.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    assert HackathonComSource().fetch() == []


def test_hackathoncom_fetch_never_raises_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.hackathoncom.get", _raise)
    assert HackathonComSource().fetch() == []


def test_parse_date_rolls_to_next_year_when_month_day_already_passed():
    today = date(2026, 8, 23)
    result = _parse_date("01 Jul", today=today)
    assert result == date(2027, 7, 1)


def test_parse_date_stays_current_year_when_still_upcoming():
    today = date(2026, 8, 23)
    result = _parse_date("16 Sep", today=today)
    assert result == date(2026, 9, 16)


def test_parse_date_none_when_missing():
    assert _parse_date(None) is None
