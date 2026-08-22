from __future__ import annotations

from datetime import date

from pipeline.dedup import dedup
from sources.base import Hackathon


def _h(source, title, starts_at=date(2026, 9, 1), **overrides):
    defaults = dict(
        source=source,
        source_id=f"{source}-{title}",
        title=title,
        url=f"https://example.com/{source}",
        starts_at=starts_at,
        ends_at=None,
        is_online=None,
        prize_text=None,
        location=None,
        themes=[],
        raw={},
    )
    defaults.update(overrides)
    return Hackathon(**defaults)


def test_no_collision_keeps_both():
    a = _h("devpost", "Hack A")
    b = _h("mlh", "Hack B")
    assert len(dedup([a, b])) == 2


def test_collision_keeps_higher_priority_source():
    devpost = _h("devpost", "Same Hack")
    reskilll = _h("reskilll", "Same Hack")

    result = dedup([reskilll, devpost])

    assert len(result) == 1
    assert result[0].source == "devpost"


def test_collision_merges_missing_fields_from_loser():
    devpost = _h("devpost", "Same Hack", prize_text=None, location=None)
    reskilll = _h("reskilll", "Same Hack", prize_text="$500", location="Delhi")

    result = dedup([devpost, reskilll])

    assert len(result) == 1
    assert result[0].source == "devpost"
    assert result[0].prize_text == "$500"
    assert result[0].location == "Delhi"


def test_different_start_dates_do_not_collide():
    a = _h("devpost", "Same Hack", starts_at=date(2026, 9, 1))
    b = _h("mlh", "Same Hack", starts_at=date(2026, 10, 1))
    assert len(dedup([a, b])) == 2


def test_unknown_source_treated_as_lowest_priority():
    known = _h("devpost", "Same Hack")
    unknown = _h("mystery-source", "Same Hack")

    result = dedup([unknown, known])

    assert result[0].source == "devpost"
