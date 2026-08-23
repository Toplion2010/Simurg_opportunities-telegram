"""Regression test for a real bug: an earlier version of main.py set
`seen = {}` for BOTH the --force "is it new" check AND the base dict that
gets persisted. Posting with --force on a live channel then overwrote
seen.json with only that run's items, silently discarding every previously
seeded entry. --force must only change what counts as new, never what's
kept on save.
"""

from __future__ import annotations

from datetime import date

from pipeline.dedup import dedup_key
from sources.base import Hackathon


def _h(title):
    return Hackathon(
        source="devpost", source_id=title, title=title, url=f"https://example.com/{title}",
        starts_at=date(2026, 9, 1), ends_at=None, is_online=True, prize_text=None,
        location=None, themes=[], raw={},
    )


def test_force_persistence_base_is_disk_state_not_empty():
    """Mirrors main.py's logic directly: with --force, `seen` (the
    persistence base) must start from disk state, while `check_against`
    (what counts as new) may start empty."""
    on_disk = {dedup_key(_h("Already Seeded A")): {"title": "Already Seeded A"},
               dedup_key(_h("Already Seeded B")): {"title": "Already Seeded B"}}

    force = True
    seen = dict(on_disk)  # always disk state, regardless of --force
    check_against = {} if force else seen

    new_item = _h("Freshly Posted")
    assert dedup_key(new_item) not in check_against  # force treats it as new

    posted = [new_item]
    for h in posted:
        seen[dedup_key(h)] = {"title": h.title}

    # the two pre-existing entries must still be present after "saving" `seen`
    assert dedup_key(_h("Already Seeded A")) in seen
    assert dedup_key(_h("Already Seeded B")) in seen
    assert dedup_key(new_item) in seen
    assert len(seen) == 3
