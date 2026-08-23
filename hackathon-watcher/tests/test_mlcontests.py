from __future__ import annotations

from datetime import date

from sources.mlcontests import MlContestsSource, _parse_date


def test_mlcontests_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("mlcontests.json")
    monkeypatch.setattr("sources.mlcontests.get", lambda *a, **k: response)

    hackathons = MlContestsSource().fetch()

    assert len(hackathons) == 6
    titles = [h.title for h in hackathons]
    assert "Project Omnibus: Optimise School Bus Routes" in titles

    online_one = next(h for h in hackathons if h.title == "Project Omnibus: Optimise School Bus Routes")
    assert online_one.source == "mlcontests"
    assert online_one.is_online is True
    assert online_one.location is None
    assert online_one.ends_at == date(2026, 8, 1)
    assert online_one.starts_at is None
    assert online_one.prize_text == "$1,200"
    assert "competition" in online_one.themes
    assert "reinforcement learning" in online_one.themes
    assert online_one.organizer == "Jane Street, AoPS, Nord Sec, Interview Buddy"

    in_person = next(h for h in hackathons if h.title == "Program Robots to Navigate Autonomously")
    assert in_person.is_online is False
    assert in_person.location == "In-person"
    assert in_person.starts_at == date(2025, 1, 1)
    assert in_person.ends_at == date(2025, 5, 1)


def test_mlcontests_returns_empty_when_data_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.mlcontests.get", lambda *a, **k: FakeResponse("{}"))
    assert MlContestsSource().fetch() == []


def test_mlcontests_fetch_never_raises_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.mlcontests.get", _raise)
    assert MlContestsSource().fetch() == []


def test_parse_date_handles_zero_padded_and_bare_day():
    assert _parse_date("1 Aug 2026") == date(2026, 8, 1)
    assert _parse_date("06 Jan 2025") == date(2025, 1, 6)


def test_parse_date_none_when_missing():
    assert _parse_date(None) is None
    assert _parse_date("") is None
