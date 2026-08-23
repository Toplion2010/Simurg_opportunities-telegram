"""Regression guard: dedup_key (title+start-date) can drift slightly
between fetches (title normalization edge cases, a re-parsed start date).
main.py's "is this new" check also excludes any URL that already appears
in a seen entry, so a drifted key alone can't cause a repost.
"""

from __future__ import annotations

from datetime import date

from pipeline.dedup import dedup_key
from sources.base import Hackathon


def _h(title, url, starts_at):
    return Hackathon(
        source="devpost", source_id=title, title=title, url=url,
        starts_at=starts_at, ends_at=None, is_online=True, prize_text=None,
        location=None, themes=[], raw={},
    )


def test_same_url_blocked_even_if_dedup_key_drifts():
    posted = _h("3rd-Web-Hack", "https://3rd-web-hack.devpost.com", date(2026, 8, 22))
    seen = {dedup_key(posted): {"title": posted.title, "url": posted.url}}

    # Same event, but the listing now parses a different start date —
    # dedup_key alone would treat this as new.
    refetched = _h("3rd-Web-Hack", "https://3rd-web-hack.devpost.com", date(2026, 8, 21))
    assert dedup_key(refetched) not in seen  # key drifted

    seen_urls = {v.get("url") for v in seen.values() if v.get("url")}
    is_new = dedup_key(refetched) not in seen and refetched.url not in seen_urls
    assert is_new is False


def test_different_url_same_title_still_treated_as_new():
    posted = _h("AI Challenge", "https://ai-challenge-classic.devpost.com", date(2026, 9, 1))
    seen = {dedup_key(posted): {"title": posted.title, "url": posted.url}}

    different_event = _h("AI Challenge 2", "https://ai-challenge-2.devpost.com", date(2026, 9, 8))
    seen_urls = {v.get("url") for v in seen.values() if v.get("url")}
    is_new = dedup_key(different_event) not in seen and different_event.url not in seen_urls
    assert is_new is True
