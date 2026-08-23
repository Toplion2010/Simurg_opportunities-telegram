from __future__ import annotations

from pipeline.normalize import canonicalize_url, normalized_title


def test_lowercases_and_strips_punctuation():
    assert normalized_title("HackMTY 2026!") == "hackmty"


def test_collapses_whitespace():
    assert normalized_title("  Global   Hack   Week  ") == "global week"


def test_drops_noise_words():
    assert normalized_title("Best Hackathon 2026") == "best"
    assert normalized_title("Hack the North") == "the north"


def test_same_event_different_titles_collide():
    a = normalized_title("Hack The North 2026")
    b = normalized_title("hack the north!")
    assert a == b


def test_canonicalize_url_strips_devpost_tracking_params():
    url = (
        "https://3rd-web-hack.devpost.com/?"
        "_gl=1*abc123&_ga=GA1.2.111.222&_ga_ABCDEF1234=GS1.1.1.1"
        "&ref_feature=challenge_home&ref_medium=discover"
    )
    assert canonicalize_url(url) == "https://3rd-web-hack.devpost.com"


def test_canonicalize_url_strips_trailing_slash():
    assert canonicalize_url("https://example.com/hackathons/") == "https://example.com/hackathons"


def test_canonicalize_url_lowercases_host():
    assert canonicalize_url("https://Example.COM/path") == "https://example.com/path"


def test_canonicalize_url_strips_fragment():
    assert canonicalize_url("https://example.com/path#section") == "https://example.com/path"


def test_canonicalize_url_no_query_or_fragment_unchanged():
    assert canonicalize_url("https://example.com/path") == "https://example.com/path"
