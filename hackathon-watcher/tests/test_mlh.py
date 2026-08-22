from __future__ import annotations

from datetime import date

from sources.mlh import MlhSource


def test_mlh_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("mlh.html")
    monkeypatch.setattr("sources.mlh.get", lambda *a, **k: response)

    hackathons = MlhSource().fetch()

    assert len(hackathons) == 2
    digital, physical = hackathons

    assert digital.title == "Test Virtual Hackathon"
    assert digital.source_id == "https://events.mlh.com/events/test-virtual-hackathon"
    assert digital.is_online is True
    assert digital.starts_at == date(2026, 8, 28)
    assert digital.ends_at == date(2026, 8, 30)
    assert digital.themes == ["Software"]

    assert physical.title == "Test Campus Hack"
    assert physical.is_online is False
    assert physical.location == "Houston, Texas"


def test_mlh_returns_empty_when_script_tag_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.mlh.get", lambda *a, **k: FakeResponse("<html><body>nope</body></html>"))
    assert MlhSource().fetch() == []
