from __future__ import annotations

from datetime import date

import config
from pipeline.telegram import _deadline_line, format_message, send_hackathon
from sources.base import Hackathon


def _h(**overrides) -> Hackathon:
    defaults = dict(
        source="devpost", source_id="1", title="Test Hack",
        url="https://example.com/hack", starts_at=date(2026, 9, 1),
        ends_at=date(2026, 9, 3), is_online=True, prize_text="$1,000",
        location="Online", themes=["AI", "Open Source"], raw={},
    )
    defaults.update(overrides)
    return Hackathon(**defaults)


TODAY = date(2026, 8, 23)


# --- deadline line -----------------------------------------------------

def test_deadline_future_shows_days_left():
    h = _h(ends_at=date(2026, 9, 4))
    assert _deadline_line(h, today=TODAY) == "⏳ 12 days left · ends 4 Sep"


def test_deadline_one_day_shows_last_day():
    h = _h(ends_at=date(2026, 8, 24))
    assert _deadline_line(h, today=TODAY) == "⏳ Last day · ends 24 Aug"


def test_deadline_today_shows_ends_today():
    h = _h(ends_at=date(2026, 8, 23))
    assert _deadline_line(h, today=TODAY) == "⏳ Ends today"


def test_deadline_past_omitted():
    h = _h(ends_at=date(2026, 8, 20))
    assert _deadline_line(h, today=TODAY) is None


def test_deadline_missing_omitted():
    h = _h(ends_at=None, deadline=None)
    assert _deadline_line(h, today=TODAY) is None


def test_deadline_prefers_enriched_deadline_over_ends_at():
    h = _h(ends_at=date(2026, 9, 1), deadline=date(2026, 9, 10))
    assert _deadline_line(h, today=TODAY) == "⏳ 18 days left · ends 10 Sep"


# --- format_message: presence/absence -----------------------------------

def test_basic_message_has_title_link_and_hashtags():
    text = format_message(_h())
    assert '<b><a href="https://example.com/hack">Test Hack</a></b>' in text
    assert "#AI #OpenSource" in text


def test_prize_and_location_share_one_line():
    text = format_message(_h(prize_text="$1,000", is_online=True))
    lines = text.split("\n")
    prize_line = next(l for l in lines if "🏆" in l)
    assert "🏆 $1,000" in prize_line
    assert "🌐 Online" in prize_line
    assert "  ·  " in prize_line


def test_in_person_shows_pin_and_location():
    text = format_message(_h(is_online=False, location="Berlin"))
    assert "📍 Berlin" in text
    assert "🌐" not in text


def test_no_prize_no_location_omits_line():
    h = _h(prize_text=None, prize_breakdown=[], is_online=None, location=None)
    text = format_message(h)
    assert "🏆" not in text
    assert "📍" not in text
    assert "🌐" not in text


def test_organizer_below_eligibility():
    text = format_message(_h(organizer="Acme Club", eligibility="Students only"))
    elig_idx = text.index("⚠️")
    org_idx = text.index("🏢")
    assert elig_idx < org_idx


def test_eligibility_absent_when_none():
    text = format_message(_h(eligibility=None))
    assert "⚠️" not in text


def test_no_date_range_line():
    """The old 📅 start->end line is gone entirely, replaced by ⏳."""
    text = format_message(_h(ends_at=date(2026, 9, 3)))
    assert "📅" not in text


def test_themes_capped_at_three():
    text = format_message(_h(themes=["A", "B", "C", "D", "E"]))
    assert "#A #B #C" in text
    assert "#D" not in text
    assert "#E" not in text


def test_no_optional_fields_no_empty_lines_or_orphan_emoji():
    h = _h(
        organizer=None, eligibility=None, themes=[], description=None,
        prize_text=None, prize_breakdown=[], is_online=None, location=None,
        ends_at=None, deadline=None,
    )
    text = format_message(h)
    assert text == '<b><a href="https://example.com/hack">Test Hack</a></b>'
    for emoji in ("🏆", "📍", "🌐", "⏳", "⚠️", "🏢", "#"):
        assert emoji not in text
    assert "\n\n" not in text


def test_description_three_sentences_no_emoji_prefix_blank_line_before():
    desc = "First sentence here. Second sentence here. Third sentence here. Fourth should not appear."
    text = format_message(_h(description=desc))
    assert "\n\nFirst sentence here. Second sentence here. Third sentence here." in text
    assert "Fourth" not in text


def test_description_html_escaped():
    text = format_message(_h(description="<script>alert(1)</script>"))
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


# --- truncation order: themes -> organizer -> eligibility -> description --

def test_truncation_never_touches_title_link():
    h = _h(description="word " * 2000, organizer="Org", themes=["A", "B", "C"], eligibility="Students only")
    text = format_message(h, max_length=200)
    assert '<b><a href="https://example.com/hack">Test Hack</a></b>' in text
    assert len(text) <= 200


def test_truncation_drops_themes_before_organizer():
    h = _h(description=None, organizer="Org", themes=["A", "B", "C"], eligibility=None)
    core_and_org_len = len(format_message(_h(description=None, organizer="Org", themes=[], eligibility=None)))
    text = format_message(h, max_length=core_and_org_len + 2)
    assert "Org" in text
    assert "#A" not in text


def test_truncation_drops_organizer_before_eligibility():
    h = _h(description=None, organizer="A Very Long Organizer Name Indeed", themes=[], eligibility="Students only")
    core_and_elig_len = len(format_message(_h(description=None, organizer=None, themes=[], eligibility="Students only")))
    text = format_message(h, max_length=core_and_elig_len + 2)
    assert "Students only" in text
    assert "A Very Long Organizer Name Indeed" not in text


def test_truncation_drops_eligibility_before_description():
    h = _h(description="First sentence here. Second sentence here.", organizer=None, themes=[], eligibility="Students only")
    core_and_desc_len = len(format_message(
        _h(description="First sentence here. Second sentence here.", organizer=None, themes=[], eligibility=None)
    ))
    text = format_message(h, max_length=core_and_desc_len + 2)
    assert "First sentence here" in text
    assert "Students only" not in text


def test_truncation_keeps_description_over_optional_fields():
    h = _h(
        description="First sentence here. Second sentence here.",
        organizer="Org", themes=["A", "B", "C"], eligibility="Students only",
    )
    core_and_desc_len = len(format_message(
        _h(description="First sentence here. Second sentence here.", organizer=None, themes=[], eligibility=None)
    ))
    text = format_message(h, max_length=core_and_desc_len + 2)
    assert "First sentence here" in text
    assert "Org" not in text
    assert "#A" not in text
    assert "Students only" not in text


# --- photo caption (1024) vs message text (4096) ------------------------

def test_photo_caption_default_is_1024_and_message_default_is_4096():
    long_desc = ("word " * 250).strip() + ". " + ("word " * 250).strip() + "."
    caption = format_message(_h(description=long_desc), max_length=1024)
    full_text = format_message(_h(description=long_desc), max_length=4096)
    assert len(caption) <= 1024
    assert len(full_text) <= 4096
    assert len(full_text) > len(caption)
    assert caption.endswith("…")


# --- send_hackathon: generation always attempted, even with a real photo --

def test_send_hackathon_tries_generation_before_real_photo(monkeypatch):
    h = _h(image_url="https://example.com/real-cover.png")
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr("pipeline.telegram.generate_image", lambda h, key: b"generated-bytes")

    calls = []
    monkeypatch.setattr(
        "pipeline.telegram.send_photo_bytes",
        lambda token, chat_id, data, caption: calls.append(("generated", data)) or True,
    )
    monkeypatch.setattr(
        "pipeline.telegram.send_photo",
        lambda token, chat_id, url, caption: calls.append(("real", url)) or True,
    )

    assert send_hackathon("tok", "chat", h, gemini_api_key="key") is True
    assert calls == [("generated", b"generated-bytes")]


def test_send_hackathon_falls_back_to_real_photo_when_generation_fails(monkeypatch):
    h = _h(image_url="https://example.com/real-cover.png")
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr("pipeline.telegram.generate_image", lambda h, key: None)

    calls = []
    monkeypatch.setattr(
        "pipeline.telegram.send_photo",
        lambda token, chat_id, url, caption: calls.append(("real", url)) or True,
    )

    assert send_hackathon("tok", "chat", h, gemini_api_key="key") is True
    assert calls == [("real", "https://example.com/real-cover.png")]


def test_send_hackathon_falls_back_to_text_when_generation_and_photo_both_fail(monkeypatch):
    h = _h(image_url="https://example.com/real-cover.png")
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr("pipeline.telegram.generate_image", lambda h, key: None)
    monkeypatch.setattr("pipeline.telegram.send_photo", lambda *a, **k: False)

    calls = []
    monkeypatch.setattr(
        "pipeline.telegram.send_message",
        lambda token, chat_id, text: calls.append(text) or True,
    )

    assert send_hackathon("tok", "chat", h, gemini_api_key="key") is True
    assert len(calls) == 1


def test_send_hackathon_skips_generation_without_api_key(monkeypatch):
    h = _h(image_url="https://example.com/real-cover.png")
    called = []
    monkeypatch.setattr(
        "pipeline.telegram.generate_image", lambda h, key: called.append(1)
    )
    monkeypatch.setattr("pipeline.telegram.send_photo", lambda *a, **k: True)

    assert send_hackathon("tok", "chat", h, gemini_api_key=None) is True
    assert called == []
