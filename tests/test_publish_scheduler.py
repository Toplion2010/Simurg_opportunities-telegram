"""The daily publish ceiling (src/publisher/scheduler.py: remaining_publish_cap).

publish_scheduled() itself does real DB + Telegram I/O and is verified the
same way batch_processor.run() and daily_digest.run() are: a live dispatched
workflow run, not a unit test (see test_daily_digest.py's docstring). The
cap arithmetic is pulled out as a pure function specifically so it CAN be
unit tested in isolation.
"""
import pytest

from src.publisher.scheduler import remaining_publish_cap


@pytest.mark.parametrize(
    "daily_cap,already_published,expected",
    [
        (7, 0, 7),
        (7, 3, 4),
        (7, 7, 0),
        (7, 10, 0),  # over cap (e.g. cap lowered mid-day) -- never negative
        (0, 0, 0),
    ],
)
def test_remaining_publish_cap(daily_cap, already_published, expected):
    assert remaining_publish_cap(daily_cap, already_published) == expected


def test_remaining_publish_cap_bounds_a_due_list_regardless_of_origin():
    # Mirrors how publish_scheduled() uses this: auto-approved-today rows and
    # a human approval from days ago sit in the same `due` list, so trimming
    # by position (oldest/most-due first, per get_due_for_publish's own
    # order) is origin-blind by design.
    due = ["auto-approved-today", "manual-approval-from-last-week", "auto-approved-today-2"]
    cap = remaining_publish_cap(daily_cap=7, already_published=6)
    assert due[:cap] == ["auto-approved-today"]
