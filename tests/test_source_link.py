from src.db.models.source_channel import SourceChannel
from src.processor.source_link import build_source_url


def test_public_channel_uses_username():
    channel = SourceChannel(telegram_id=123456789, username="somechannel")
    assert build_source_url(channel, 42) == "https://t.me/somechannel/42"


def test_private_channel_without_username_uses_c_form():
    channel = SourceChannel(telegram_id=123456789, username=None)
    assert build_source_url(channel, 42) == "https://t.me/c/123456789/42"


def test_missing_channel_returns_none():
    assert build_source_url(None, 42) is None
