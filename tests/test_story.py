"""Starred Telegram Stories (src/publisher/story.py) and the published-message
reference sender.py records for them.

publish_stories() itself does real DB + Telegram I/O and is verified the same
way publish_scheduled() is: a live workflow run. What's covered here is the
logic around it -- targets, caption, reposting the live message's own photo,
partial/total failure -- against a fake Telethon client.
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import InputMediaPhoto, InputPhoto, Photo

import src.publisher.image_gen as image_gen
import src.publisher.story as story
from src.core.config import Settings
from src.core.enums import Audience, Category, OpportunityStatus
from src.core.exceptions import PublishError
from src.db.models.opportunity import Opportunity
from src.publisher.sender import OpportunitySender
from src.publisher.story import post_story, story_caption, story_targets

SCHOOL = -1001
UNIVERSITY = -1002
HACKATHON = -1003


def make_settings(**overrides) -> Settings:
    base = dict(
        BOT_TOKEN="x",
        ADMIN_IDS=[1],
        TELETHON_API_ID=1,
        TELETHON_API_HASH="x",
        DEST_CHANNEL_ID_SCHOOL=SCHOOL,
        DEST_CHANNEL_ID_UNIVERSITY=UNIVERSITY,
        DEST_CHANNEL_ID_HACKATHON=HACKATHON,
        DATABASE_URL="postgresql+asyncpg://u:p@h/db",
    )
    base.update(overrides)
    return Settings(**base)


def make_opp(**overrides) -> Opportunity:
    fields = dict(
        id=7,
        title="Global AI Hackathon",
        deadline="12 October 2026",
        category=Category.Hackathon,
        audience=Audience.university,
        location="Online",
        status=OpportunityStatus.published,
        published_chat_id=UNIVERSITY,
        published_message_id=555,
    )
    fields.update(overrides)
    return Opportunity(**fields)


LIVE_PHOTO = Photo(
    id=111, access_hash=222, file_reference=b"ref", date=None, sizes=[], dc_id=2
)


class FakeClient:
    def __init__(self, photo=LIVE_PHOTO, fail_on=(), deleted_message_ids=()):
        self._photo = photo
        self._fail_on = set(fail_on)
        self._deleted = set(deleted_message_ids)
        self.fetched: list[tuple[int, int]] = []
        self.stories: list[tuple[int, SendStoryRequest]] = []

    def is_connected(self):
        return True

    async def get_dialogs(self, limit=None):
        return []

    async def get_messages(self, chat_id, ids):
        self.fetched.append((chat_id, ids))
        if self._photo is False or ids in self._deleted:
            return None
        return SimpleNamespace(photo=self._photo)

    async def get_entity(self, chat_id):
        return chat_id

    async def __call__(self, request):
        if request.peer in self._fail_on:
            raise RuntimeError("CHAT_ADMIN_REQUIRED")
        self.stories.append((request.peer, request))


# --- targets & caption --------------------------------------------------------


def test_story_goes_to_all_three_channels_regardless_of_audience():
    assert story_targets(make_settings()) == [SCHOOL, UNIVERSITY, HACKATHON]


def test_unset_hackathon_channel_is_skipped():
    assert story_targets(make_settings(DEST_CHANNEL_ID_HACKATHON=0)) == [SCHOOL, UNIVERSITY]


def test_duplicate_channel_ids_post_once():
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=SCHOOL)
    assert story_targets(settings) == [SCHOOL, UNIVERSITY]


def test_caption_has_title_and_deadline():
    assert story_caption(make_opp()) == "✨ Global AI Hackathon\n⏳ 12 October 2026"


def test_caption_without_deadline_is_title_only():
    assert story_caption(make_opp(deadline=None)) == "✨ Global AI Hackathon"


def test_caption_fits_telegram_story_limit():
    assert len(story_caption(make_opp(title="x" * 500))) == 200


# --- post_story ---------------------------------------------------------------


def test_reposts_the_live_messages_own_photo_to_every_channel():
    client = FakeClient()
    result = asyncio.run(post_story(make_settings(), client, make_opp()))

    assert client.fetched == [(UNIVERSITY, 555)]
    assert result.succeeded == [SCHOOL, UNIVERSITY, HACKATHON]
    assert result.failed == []
    for _, request in client.stories:
        # Referenced by id -- the same photo that's live, never a re-render.
        assert isinstance(request.media, InputMediaPhoto)
        assert request.media.id == InputPhoto(id=111, access_hash=222, file_reference=b"ref")
        assert request.period == 24 * 60 * 60
        assert request.caption == "✨ Global AI Hackathon\n⏳ 12 October 2026"


def test_one_channel_failing_is_a_partial_success():
    client = FakeClient(fail_on={HACKATHON})
    result = asyncio.run(post_story(make_settings(), client, make_opp()))

    assert result.succeeded == [SCHOOL, UNIVERSITY]
    assert [c for c, _ in result.failed] == [HACKATHON]


def test_every_channel_failing_raises():
    client = FakeClient(fail_on={SCHOOL, UNIVERSITY, HACKATHON})
    with pytest.raises(PublishError):
        asyncio.run(post_story(make_settings(), client, make_opp()))


@pytest.mark.parametrize("photo", [False, None], ids=["message-deleted", "no-photo"])
def test_missing_live_photo_raises_before_posting_anything(photo):
    client = FakeClient(photo=photo)
    with pytest.raises(PublishError):
        asyncio.run(post_story(make_settings(), client, make_opp()))
    assert client.stories == []


# --- publish_stories loop -----------------------------------------------------


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.commits += 1


class AlertBot:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text):
        self.sent.append(text)


def test_one_failed_story_is_unqueued_and_does_not_block_the_rest(monkeypatch):
    requested = datetime(2026, 10, 1)
    broken = make_opp(id=1, title="Deleted post", published_message_id=1, story_requested_at=requested)
    good = make_opp(id=2, title="Cool hackathon", published_message_id=2, story_requested_at=requested)

    async def fake_pending(self):
        return [broken, good]

    monkeypatch.setattr(story.OpportunityRepository, "get_story_pending", fake_pending)
    session = FakeSession()
    bot = AlertBot()
    client = FakeClient(deleted_message_ids={1})

    asyncio.run(story.publish_stories(make_settings(), lambda: session, bot, client))

    assert broken.story_requested_at is None  # un-queued, not retried every run
    assert broken.story_posted_at is None
    assert good.story_posted_at is not None
    assert {peer for peer, _ in client.stories} == {SCHOOL, UNIVERSITY, HACKATHON}
    assert len(bot.sent) == 1 and "Deleted post" in bot.sent[0] and "Cool hackathon" not in bot.sent[0]


def test_no_client_leaves_stories_queued(monkeypatch):
    opp = make_opp(story_requested_at=datetime(2026, 10, 1))

    async def fake_pending(self):
        return [opp]

    monkeypatch.setattr(story.OpportunityRepository, "get_story_pending", fake_pending)
    asyncio.run(story.publish_stories(make_settings(), lambda: FakeSession(), AlertBot(), None))

    assert opp.story_requested_at is not None
    assert opp.story_posted_at is None


# --- sender.publish records the live message ----------------------------------


class FakeBot:
    def __init__(self, fail_on=()):
        self._fail_on = set(fail_on)
        self._next_id = 100

    async def send_photo(self, chat_id, **_):
        if chat_id in self._fail_on:
            raise RuntimeError("Forbidden")
        self._next_id += 1
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=self._next_id)

    async def set_message_reaction(self, **_):
        pass


@pytest.fixture
def no_render(monkeypatch):
    async def fake_card(opp):
        return b"jpeg"

    monkeypatch.setattr(image_gen, "generate_card", fake_card)


def test_publish_records_first_successful_channel_message(no_render):
    opp = make_opp(audience=Audience.both, published_chat_id=None, published_message_id=None)
    asyncio.run(OpportunitySender(make_settings()).publish(opp, FakeBot()))

    assert (opp.published_chat_id, opp.published_message_id) == (SCHOOL, 101)


def test_publish_skips_a_failed_first_channel_when_recording(no_render):
    opp = make_opp(audience=Audience.both, published_chat_id=None, published_message_id=None)
    asyncio.run(OpportunitySender(make_settings()).publish(opp, FakeBot(fail_on={SCHOOL})))

    assert (opp.published_chat_id, opp.published_message_id) == (UNIVERSITY, 101)
