import pytest

from src.links.redirect import append_utm, extract_slug, is_bot

UTM = dict(source="simurg_hackathons", medium="telegram")


def test_appends_full_utm_set():
    assert append_utm(
        "https://finance-cybersecurity2026.devpost.com/",
        "financial-cybersecurity-challenge-2026", **UTM,
    ) == (
        "https://finance-cybersecurity2026.devpost.com/?utm_source=simurg_hackathons"
        "&utm_medium=telegram&utm_campaign=financial-cybersecurity-challenge-2026"
    )


def test_preserves_existing_query_verbatim():
    out = append_utm("https://x.test/e?ref=abc&q=a%20b", "slug", **UTM)
    assert out.startswith("https://x.test/e?ref=abc&q=a%20b&utm_source=simurg_hackathons")


def test_never_overwrites_existing_utm_keys():
    out = append_utm("https://x.test/?utm_source=partner&UTM_MEDIUM=email", "slug", **UTM)
    assert "utm_source=partner" in out
    assert "simurg_hackathons" not in out
    assert out.count("utm_medium") + out.count("UTM_MEDIUM") == 1
    assert out.endswith("&utm_campaign=slug")


def test_fragment_kept_after_query():
    assert append_utm("https://x.test/p#prizes", "s", **UTM) == (
        "https://x.test/p?utm_source=simurg_hackathons&utm_medium=telegram&utm_campaign=s#prizes"
    )


def test_minimum_only_source():
    assert append_utm("https://x.test/", None, source="simurg_hackathons") == (
        "https://x.test/?utm_source=simurg_hackathons"
    )


@pytest.mark.parametrize("url", ["mailto:a@b.c", "javascript:alert(1)", "not a url", ""])
def test_non_web_urls_untouched(url):
    assert append_utm(url, "s", **UTM) == url


@pytest.mark.parametrize("path, slug", [
    ("/codered-orion", "codered-orion"),
    ("/BCH-BLAZE-2026/", "bch-blaze-2026"),
    ("codered-orion?x=1", "codered-orion"),
    ("/", None),
    ("/api/webhook", None),
    ("/api", None),
    ("/setup", None),
    ("/favicon.ico", None),
    ("/-leading-hyphen", None),
])
def test_extract_slug(path, slug):
    assert extract_slug(path) == slug


def test_preview_bots_are_not_counted():
    assert is_bot("TelegramBot (like TwitterBot)")
    assert is_bot("facebookexternalhit/1.1")
    assert not is_bot("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Telegram")
    assert not is_bot(None)
