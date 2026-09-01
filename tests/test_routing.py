"""Publish-target routing: audience channels, plus the KZ-hackathon channel.

``_resolve_targets`` is a pure function of (Settings, Opportunity) — no DB, no
network — and sender.py imports image_gen lazily inside publish(), so nothing
here pulls Playwright into CI.
"""
import pytest

from src.core.config import Settings
from src.core.enums import Audience, Category
from src.db.models.opportunity import Opportunity
from src.publisher.sender import OpportunitySender

SCHOOL = -1001
UNIVERSITY = -1002
HACKATHON = -1003


def make_settings(**overrides) -> Settings:
    # A real Settings rather than a stub, so the sentinel default and the
    # blank-to-off validator are exercised by every case below.
    base = dict(
        BOT_TOKEN="x",
        ADMIN_IDS=[1],
        TELETHON_API_ID=1,
        TELETHON_API_HASH="x",
        DEST_CHANNEL_ID_SCHOOL=SCHOOL,
        DEST_CHANNEL_ID_UNIVERSITY=UNIVERSITY,
        DATABASE_URL="postgresql+asyncpg://u:p@h/db",
    )
    base.update(overrides)
    return Settings(**base)


def make_opp(*, category=Category.Hackathon, location="Almaty", audience=Audience.both):
    # Transient, never added to a session — these three fields are all that
    # routing reads.
    return Opportunity(id=1, category=category, location=location, audience=audience)


def targets_for(settings: Settings, opp: Opportunity) -> list[int]:
    return OpportunitySender(settings)._resolve_targets(opp)


def test_kz_hackathon_also_goes_to_the_hackathon_channel():
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    # Additive: it keeps both audience channels AND gains the third.
    assert targets_for(settings, make_opp()) == [SCHOOL, UNIVERSITY, HACKATHON]


def test_extra_channel_is_last():
    # If a rate limit hits mid-loop, the audience channels must already be out.
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    assert targets_for(settings, make_opp())[-1] == HACKATHON


def test_non_kz_hackathon_is_not_routed():
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    opp = make_opp(location="Berlin, Germany")
    assert targets_for(settings, opp) == [SCHOOL, UNIVERSITY]


@pytest.mark.parametrize("location", [None, "", "Online", "Remote", "Worldwide"])
def test_no_kz_signal_is_not_routed(location):
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    assert targets_for(settings, make_opp(location=location)) == [SCHOOL, UNIVERSITY]


def test_kz_non_hackathon_is_not_routed():
    # The channel is category-scoped: a KZ scholarship does not belong there.
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    opp = make_opp(category=Category.Scholarship)
    assert targets_for(settings, opp) == [SCHOOL, UNIVERSITY]


def test_unset_channel_is_a_silent_no_op():
    # The sentinel default — feature off, nothing routed, no crash.
    settings = make_settings()
    assert settings.DEST_CHANNEL_ID_HACKATHON == 0
    assert targets_for(settings, make_opp()) == [SCHOOL, UNIVERSITY]


def test_blank_secret_does_not_break_boot():
    # GitHub Actions expands a missing secret to "" and still sets the env var.
    # Without the mode="before" validator this raises and every batch and drain
    # run dies at boot.
    assert make_settings(DEST_CHANNEL_ID_HACKATHON="").DEST_CHANNEL_ID_HACKATHON == 0
    assert make_settings(DEST_CHANNEL_ID_HACKATHON=None).DEST_CHANNEL_ID_HACKATHON == 0


def test_audience_school_keeps_its_single_channel():
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    opp = make_opp(audience=Audience.school)
    assert targets_for(settings, opp) == [SCHOOL, HACKATHON]


def test_audience_university_keeps_its_single_channel():
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    opp = make_opp(audience=Audience.university)
    assert targets_for(settings, opp) == [UNIVERSITY, HACKATHON]


def test_missing_category_does_not_crash():
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    assert targets_for(settings, make_opp(category=None)) == [SCHOOL, UNIVERSITY]


def test_duplicate_chat_id_is_not_double_posted():
    # A fat-fingered secret equal to the school id must not send twice.
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=SCHOOL)
    targets = targets_for(settings, make_opp())
    assert targets == [SCHOOL, UNIVERSITY]
    assert targets.count(SCHOOL) == 1
