"""Deadline parsing and deadline-ordered publishing.

The motivating incident: a hackathon whose registration closed on 12 September
2026 was published on the 13th. `deadline` is free text with no parsed column,
and get_due_for_publish orders by approval time, so nothing in the pipeline
had ever looked at the date.

The asymmetry these tests pin down: sorting a live post late is a nuisance,
dropping a live post as expired is content the channel never sees. So every
uncertain input must resolve to "not expired", never to a guess.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from src.publisher.deadlines import deadline_sort_key, is_expired, parse_deadline
from src.publisher.scheduler import partition_by_deadline

TODAY = date(2026, 9, 13)


@pytest.mark.parametrize(
    "text,expected",
    [
        # The exact string from the post that went out a day late.
        ("12 September 2026", date(2026, 9, 12)),
        # Real values carry the formatter's prose around them.
        ("Registration closes: 12 September 2026", date(2026, 9, 12)),
        ("applications must be submitted by 12 September 2026", date(2026, 9, 12)),
        ("September 12, 2026", date(2026, 9, 12)),
        ("Sept 30 2026", date(2026, 9, 30)),
        ("March 20, 2025", date(2025, 3, 20)),
        ("2026-09-12", date(2026, 9, 12)),
        ("apply by 1st October 2026", date(2026, 10, 1)),
        ("25/09/2026", date(2026, 9, 25)),  # 25 > 12 settles day-first
        ("09/25/2026", date(2026, 9, 25)),  # 25 > 12 settles month-first
    ],
)
def test_parses_real_world_deadlines(text, expected):
    assert parse_deadline(text, TODAY) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Rolling",
        "Ongoing until filled",
        "TBA",
        "Unknown",
        "12/09/2026",  # day-first or month-first? unknowable -- do not guess
        "31 February 2026",  # not a date; the LLM does slip
    ],
)
def test_undated_and_ambiguous_text_is_not_a_date(text):
    assert parse_deadline(text, TODAY) is None
    assert is_expired(text, TODAY) is False


def test_deadline_today_is_not_expired():
    """An application due the 12th is open for all of the 12th."""
    assert is_expired("12 September 2026", date(2026, 9, 12)) is False
    assert is_expired("12 September 2026", date(2026, 9, 13)) is True


def test_yearless_deadline_resolves_forward():
    """"12 September" with the 12th already past means next year's, not a date
    three days ago -- the reading that cannot retire a still-open row."""
    assert parse_deadline("12 September", TODAY) == date(2027, 9, 12)
    assert is_expired("12 September", TODAY) is False


def test_undated_sorts_after_every_dated_row():
    assert deadline_sort_key("Rolling", TODAY) > deadline_sort_key("31 December 2099", TODAY)


def _opp(id_: int, deadline: str | None):
    return SimpleNamespace(id=id_, deadline=deadline)


def test_partition_orders_soonest_first_and_drops_the_expired():
    # Deliberately in approval order, which is what get_due_for_publish returns
    # and what previously decided who got the day's slots.
    due = [
        _opp(1, "12 September 2026"),  # closed yesterday
        _opp(2, "Rolling"),
        _opp(3, "30 September 2026"),
        _opp(4, "15 September 2026"),  # closes in two days -- most urgent
    ]

    live, expired = partition_by_deadline(due, TODAY)

    assert [o.id for o in live] == [4, 3, 2]
    assert [o.id for o in expired] == [1]


def test_the_urgent_row_survives_the_cap_that_used_to_trim_it():
    """The cap trims by position, so ordering is what decides which posts go
    out -- this is the whole point of sorting before trimming."""
    due = [_opp(1, "Rolling"), _opp(2, "31 December 2026"), _opp(3, "14 September 2026")]

    live, _ = partition_by_deadline(due, TODAY)

    assert [o.id for o in live[:1]] == [3]


def test_partition_keeps_everything_it_does_not_expire():
    due = [_opp(1, "Rolling"), _opp(2, None), _opp(3, "1 December 2026")]

    live, expired = partition_by_deadline(due, TODAY)

    assert len(live) == 3 and expired == []
