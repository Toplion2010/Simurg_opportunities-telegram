"""Automatic posting rules: 75+ auto-approve with a 60+ daily pick
(daily_digest.route_candidates), automatic Stories for big-prize hackathons
(core/prize.py, publisher/story.wants_auto_story), and "N days left" reminder
posts (publisher/reminders.due_reminders, OpportunitySender.publish_reminder).
"""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import src.publisher.image_gen as image_gen
from src.core.config import Settings
from src.core.enums import Audience, Category, OpportunityStatus
from src.core.prize import opportunity_prize_usd, prize_usd
from src.db.models.opportunity import Opportunity
from src.publisher.reminders import due_reminders
from src.publisher.sender import OpportunitySender
from src.publisher.story import wants_auto_story
from src.routines.daily_digest import route_candidates

TODAY = date(2026, 10, 1)


def make_opp(**overrides) -> Opportunity:
    fields = dict(
        id=1,
        title="Opportunity",
        category=Category.Hackathon,
        audience=Audience.school,
        location="Online",
        status=OpportunityStatus.published,
        relevance=72,
        deadline="15 October 2026",
        published_at=datetime(2026, 9, 1),
        published_chat_id=-1001,
        published_message_id=10,
    )
    fields.update(overrides)
    return Opportunity(**fields)


def test_defaults_match_the_agreed_rules():
    d = {name: field.default for name, field in Settings.model_fields.items()}
    assert d["AUTO_APPROVE_SCORE"] == 75
    assert d["DAILY_PICK_MIN_SCORE"] == 60
    assert d["AUTO_STORY_PRIZE_USD"] == 5000
    assert d["REMINDER_MIN_SCORE"] == 70
    assert d["REMINDER_DAYS_BEFORE"] == 14


# --- prize parsing ------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$50,000 prize pool", 50_000),
        ("$10K in prizes", 10_000),
        ("$1.5M", 1_500_000),
        ("5 000 USD", 5_000),
        ("$ 7 500", 7_500),
        ("€5000", 5_400),
        ("Total 3 000 000 KZT and merch", 6_250),
        ("1,5 млн тенге", 3_125),
        ("призовой фонд 500 000 рублей", 500_000 / 90),
        ("Grand prize: USD 3,000; 2nd: USD 1,500", 3_000),
    ],
)
def test_prize_amounts(text, expected):
    assert prize_usd(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text", [None, "", "2026 hackathon, teams of 4, 48 hours", "Certificates and merch"]
)
def test_no_currency_amount_means_no_prize(text):
    assert prize_usd(text) is None


def test_description_only_used_when_rewards_are_empty():
    # Rewards say "certificates": the tuition-like money in the description
    # must not count as a prize.
    assert opportunity_prize_usd(make_opp(rewards="Certificates", description="Fee $20,000")) is None
    assert opportunity_prize_usd(make_opp(rewards=None, description="Prize pool $8,000")) == 8_000


# --- automatic story ----------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (dict(rewards="$5,000 prize pool"), True),
        (dict(rewards="$4,999"), False),
        (dict(rewards="Certificates"), False),
        (dict(rewards="$50,000", category=Category.Scholarship), False),
        (dict(rewards="$50,000", story_requested_at=datetime(2026, 10, 1)), False),
    ],
    ids=["5k-hackathon", "under-5k", "no-money", "not-hackathon", "already-queued"],
)
def test_auto_story_rule(overrides, expected):
    assert wants_auto_story(make_opp(**overrides), 5000) is expected


# --- auto-approve + daily pick ------------------------------------------------


def _scored(*scores):
    return [make_opp(id=i, relevance=s) for i, s in enumerate(scores)]


def test_75_plus_are_all_auto_approved_and_no_daily_pick():
    auto, pick, review = route_candidates(_scored(80, 76, 70, 50), 75, 60)
    assert [o.relevance for o in auto] == [80, 76]
    assert pick is None
    assert [o.relevance for o in review] == [70, 50]


def test_no_75_plus_means_best_60_plus_is_the_daily_pick():
    auto, pick, review = route_candidates(_scored(68, 61, 45), 75, 60)
    assert auto == []
    assert pick.relevance == 68
    assert [o.relevance for o in review] == [61, 45]


def test_no_daily_pick_when_best_is_under_60():
    auto, pick, review = route_candidates(_scored(59, 41), 75, 60)
    assert auto == [] and pick is None
    assert len(review) == 2


def test_unscored_candidate_is_never_auto_approved():
    auto, pick, review = route_candidates(_scored(None), 75, 60)
    assert auto == [] and pick is None and len(review) == 1


# --- reminder selection -------------------------------------------------------


def test_reminder_window_is_1_to_14_days_soonest_first():
    opps = [
        make_opp(id=1, deadline="15 October 2026"),  # 14 days
        make_opp(id=2, deadline="3 October 2026"),  # 2 days
        make_opp(id=3, deadline="16 October 2026"),  # 15 days: too early
        make_opp(id=4, deadline="1 October 2026"),  # today: too late
        make_opp(id=5, deadline="Rolling"),  # unparseable
    ]
    assert [(o.id, d) for o, d in due_reminders(opps, TODAY, 14)] == [(2, 2), (1, 14)]


def test_no_reminder_right_after_the_original_post():
    fresh = make_opp(id=1, published_at=datetime(2026, 9, 28))  # 3 days ago
    old = make_opp(id=2, published_at=datetime(2026, 9, 24))  # 7 days ago
    assert [o.id for o, _ in due_reminders([fresh, old], TODAY, 14)] == [2]


# --- reminder post ------------------------------------------------------------


class FakeBot:
    def __init__(self):
        self.captions: list[tuple[int, str]] = []

    async def send_photo(self, chat_id, caption, **_):
        self.captions.append((chat_id, caption))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=999)

    async def send_message(self, **_):
        pass

    async def set_message_reaction(self, **_):
        pass


def test_reminder_is_a_new_image_with_banner_and_keeps_the_original_reference(monkeypatch):
    renders = []

    async def fake_card(opp):
        renders.append(opp.id)
        return b"jpeg"

    monkeypatch.setattr(image_gen, "generate_card", fake_card)
    settings = Settings(
        BOT_TOKEN="x", TELETHON_API_ID=1, TELETHON_API_HASH="x",
        DEST_CHANNEL_ID_SCHOOL=-1001, DEST_CHANNEL_ID_UNIVERSITY=-1002,
        DATABASE_URL="postgresql+asyncpg://u:p@h/db",
    )
    opp = make_opp(title="Global Hackathon", category=Category.Scholarship)
    bot = FakeBot()

    asyncio.run(OpportunitySender(settings).publish_reminder(opp, bot, 14))

    assert renders == [1]  # a fresh image, not the old one
    [(chat_id, caption)] = bot.captions
    assert chat_id == -1001  # same routing as the original (school audience)
    assert caption.startswith("⏰ <b>14 days left to apply!</b>\n\n")
    assert "Global Hackathon" in caption
    assert len(caption) <= 1024
    # The story/reference to the ORIGINAL post is untouched.
    assert (opp.published_message_id, opp.status) == (10, OpportunityStatus.published)
