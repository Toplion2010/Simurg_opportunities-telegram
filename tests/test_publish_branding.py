"""Per-channel Simurg branding on the main publisher: card stamp, caption
footer, and About trimming that ends on a complete sentence."""
import asyncio
import io
from datetime import date

import pytest

from src.core.enums import Audience, Category
from src.db.models.opportunity import Opportunity
from src.publisher.formatter import _fit_caption, attribution_footer, format_opportunity
from src.publisher.sender import OpportunitySender
from tests.test_routing import HACKATHON, SCHOOL, UNIVERSITY, make_settings

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from src.publisher.branding import ChannelBrand, brand_card  # noqa: E402


def _card() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1200, 628), (10, 20, 40)).save(out, format="JPEG")
    return out.getvalue()


def _opp(**kw) -> Opportunity:
    base = dict(
        id=7, title="Build with AI Basics", category=Category.Hackathon, audience=Audience.both,
        location="Online", deadline="2026-10-27", apply_link="https://learn-ai-basics.devpost.com/",
        description="Build a small app. Use a coding agent. Ship one complete journey.",
        hooks=[], additional_links=[],
    )
    base.update(kw)
    return Opportunity(**base)


# --- About trimming: complete sentences, never an invented ellipsis -----------

def test_fit_caption_ends_on_complete_sentence():
    about = ("Build a small application for work or everyday life. Use a skills-compatible "
             "coding agent such as Codex. Capture boundaries in scope.md, user needs in prd.md "
             "and implementation notes in plan.md before you start coding anything at all.")
    text = f"<b>✨ T</b>\n\n📝 <b>About:</b>\n{about}\n\n🔗 <b>Register →</b> x\n\n——\n<i>#Hackathon</i>"
    fitted = _fit_caption(text, len(text) - 60)
    assert "…" not in fitted
    assert "coding agent such as Codex.\n\n🔗" in fitted
    assert "Capture boundaries" not in fitted


def test_fit_caption_drops_about_when_no_sentence_fits():
    text = "<b>T</b>\n\n📝 <b>About:</b>\n" + "word " * 60 + "\n\n——\n<i>#x</i>"
    fitted = _fit_caption(text, 60)
    assert "About" not in fitted and "…" not in fitted


def test_attribution_footer():
    assert attribution_footer("@simurg_hackathons", date(2026, 10, 12)) == (
        "✓ Checked by Simurg · 12 Oct\n@simurg_hackathons"
    )


# --- card stamp ------------------------------------------------------------

def test_brand_card_changes_footer_and_keeps_size():
    out = brand_card(_card(), ChannelBrand("SIMURG HACKATHONS", "@simurg_hackathons"), date(2026, 10, 12))
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (1200, 628)
        assert img.getpixel((600, 620)) != (10, 20, 40)


def test_brand_card_never_raises():
    assert brand_card(b"junk", ChannelBrand("X", "@x")) == b"junk"


# --- sender: each channel gets its own card + footer ------------------------

class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat_id, photo, caption, parse_mode):
        self.sent.append((chat_id, photo.data, caption))
        return type("Msg", (), {"message_id": len(self.sent), "chat": type("C", (), {"id": chat_id})})()

    async def send_message(self, **kw):
        return None


def test_each_target_gets_its_own_brand_and_footer(monkeypatch):
    settings = make_settings(DEST_CHANNEL_ID_HACKATHON=HACKATHON)
    sender = OpportunitySender(settings)
    brands = {}

    async def fake_card(opp):
        return _card()

    def fake_brand(img, brand, checked_on):
        brands[brand.handle] = brand.name
        return f"card-for-{brand.handle}".encode()

    async def no_reactions(*a, **k):
        return None

    monkeypatch.setattr("src.publisher.image_gen.generate_card", fake_card)
    monkeypatch.setattr("src.publisher.branding.brand_card", fake_brand)
    monkeypatch.setattr("src.publisher.sender.add_reactions", no_reactions)

    bot = FakeBot()
    result, _ = asyncio.run(sender._send_card(_opp(), bot, [SCHOOL, UNIVERSITY, HACKATHON], banner=""))

    assert result.succeeded == [SCHOOL, UNIVERSITY, HACKATHON]
    by_chat = {chat: (photo, caption) for chat, photo, caption in bot.sent}
    assert by_chat[HACKATHON][0] == b"card-for-@simurg_hackathons"
    assert by_chat[HACKATHON][1].endswith("@simurg_hackathons")
    assert by_chat[SCHOOL][1].endswith("@simurg_opportunities")
    assert by_chat[UNIVERSITY][1].endswith("@Simurg_Opportunities_University")
    assert "✓ Checked by Simurg ·" in by_chat[SCHOOL][1]
    assert brands["@simurg_hackathons"] == "SIMURG HACKATHONS"
    assert all(len(caption) <= 1024 for _, _, caption in bot.sent)


def test_branding_can_be_disabled(monkeypatch):
    sender = OpportunitySender(make_settings(ENABLE_CARD_BRANDING=False))
    raw = _card()
    assert sender._branded(raw, "@x", date(2026, 10, 12)) is raw


def test_long_description_caption_still_fits_with_footer():
    long = " ".join(f"Sentence number {i} is here." for i in range(200))
    text = format_opportunity(_opp(description=long), max_length=1024 - 60)
    assert len(text) <= 1024 - 60
    assert "…" not in text
