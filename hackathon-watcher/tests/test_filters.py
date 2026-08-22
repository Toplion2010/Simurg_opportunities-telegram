from __future__ import annotations

from datetime import date, timedelta

import config
from pipeline.filters import exclude_themes, include_themes, min_prize, online_only, still_open
from sources.base import Hackathon


def _h(**overrides):
    defaults = dict(
        source="devpost",
        source_id="1",
        title="Hack",
        url="https://example.com",
        starts_at=date(2026, 1, 1),
        ends_at=None,
        is_online=None,
        prize_text=None,
        location=None,
        themes=[],
        raw={},
    )
    defaults.update(overrides)
    return Hackathon(**defaults)


def test_online_only_drops_explicit_offline(monkeypatch):
    monkeypatch.setattr(config, "ONLINE_ONLY", True)
    online = _h(is_online=True)
    offline = _h(is_online=False)
    unknown = _h(is_online=None)

    result = online_only([online, offline, unknown])

    assert online in result
    assert unknown in result  # unknown is kept, not penalized
    assert offline not in result


def test_online_only_disabled_keeps_everything(monkeypatch):
    monkeypatch.setattr(config, "ONLINE_ONLY", False)
    offline = _h(is_online=False)
    assert online_only([offline]) == [offline]


def test_still_open_drops_past_end_dates(monkeypatch):
    monkeypatch.setattr(config, "STILL_OPEN", True)
    past = _h(ends_at=date.today() - timedelta(days=5))
    future = _h(ends_at=date.today() + timedelta(days=5))
    unknown = _h(ends_at=None)

    result = still_open([past, future, unknown])

    assert past not in result
    assert future in result
    assert unknown in result


def test_min_prize_keeps_unparseable(monkeypatch):
    monkeypatch.setattr(config, "MIN_PRIZE", 1000.0)
    unparseable = _h(prize_text="lots of swag")
    below = _h(prize_text="$100")
    above = _h(prize_text="$5,000")

    result = min_prize([unparseable, below, above])

    assert unparseable in result
    assert below not in result
    assert above in result


def test_min_prize_disabled_keeps_everything(monkeypatch):
    monkeypatch.setattr(config, "MIN_PRIZE", None)
    low = _h(prize_text="$1")
    assert min_prize([low]) == [low]


def test_exclude_themes(monkeypatch):
    monkeypatch.setattr(config, "EXCLUDE_THEMES", ["Web3"])
    excluded = _h(themes=["Web3", "AI"])
    kept = _h(themes=["AI"])

    result = exclude_themes([excluded, kept])

    assert excluded not in result
    assert kept in result


def test_include_themes(monkeypatch):
    monkeypatch.setattr(config, "INCLUDE_THEMES", ["AI"])
    matching = _h(themes=["AI", "Web"])
    not_matching = _h(themes=["Blockchain"])

    result = include_themes([matching, not_matching])

    assert matching in result
    assert not_matching not in result
