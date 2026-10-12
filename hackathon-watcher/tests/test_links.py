from __future__ import annotations

from datetime import date

import pytest

from pipeline.links import (
    LinkRegistry,
    _to_libpq_dsn,
    public_url,
    slug_candidates,
    slugify,
)
from sources.base import Hackathon


def _h(title: str, **kw) -> Hackathon:
    defaults = dict(
        source="devpost", source_id="1", title=title, url=f"https://x.test/{title}",
        starts_at=date(2026, 9, 1), ends_at=date(2026, 10, 11), is_online=True,
        prize_text=None, location=None,
    )
    defaults.update(kw)
    return Hackathon(**defaults)


@pytest.mark.parametrize("title, slug", [
    ("Financial Cybersecurity Challenge 2026", "financial-cybersecurity-challenge-2026"),
    ("CodeRED: Orion", "codered-orion"),
    ("Qloo LLM Hackathon", "qloo-llm-hackathon"),
    ("BCH BLAZE 2026", "bch-blaze-2026"),
    ("PayPal AI Hackathon", "paypal-ai-hackathon"),
    ("Women's Hack Night", "womens-hack-night"),
    ("Café & Code — São Paulo!", "cafe-and-code-sao-paulo"),
    ("  --Weird   spacing--  ", "weird-spacing"),
])
def test_slugify_examples(title, slug):
    assert slugify(title) == slug


def test_slugify_cuts_long_titles_on_word_boundary():
    slug = slugify("word " * 40)
    assert len(slug) <= 80
    assert not slug.endswith("-")
    assert all(part == "word" for part in slug.split("-"))


def test_collision_ladder_year_then_organizer_then_number():
    cands = slug_candidates(_h("Orion Hacks", organizer="CougarCS"))
    assert cands[:4] == [
        "orion-hacks", "orion-hacks-2026", "orion-hacks-cougarcs", "orion-hacks-2026-cougarcs",
    ]
    assert cands[4] == "orion-hacks-2"


def test_year_not_repeated_when_title_has_one():
    cands = slug_candidates(_h("BCH BLAZE 2026", organizer="Bitcoin Cash"))
    assert "bch-blaze-2026-2026" not in cands
    assert cands[1] == "bch-blaze-2026-bitcoin-cash"


def test_generic_title_gets_organizer_up_front():
    assert slug_candidates(_h("AI Hackathon", organizer="Qloo"))[0] == "qloo-ai-hackathon"


def test_non_latin_title_falls_back_to_organizer():
    assert slug_candidates(_h("黑客松", organizer="DoraHacks"))[0] == "dorahacks-hackathon"


def test_reserved_slugs_never_offered():
    assert "api" not in slug_candidates(_h("API"))


class FakeStore:
    def __init__(self, taken: dict[str, str] | None = None):
        self.rows = dict(taken or {})  # slug -> url

    def find_by_url(self, url):
        return next((s for s, u in self.rows.items() if u == url), None)

    def try_insert(self, slug, url, title, source):
        if slug in self.rows:
            return False
        self.rows[slug] = url
        return True


def test_registry_mints_branded_url():
    reg = LinkRegistry(FakeStore(), base_url="https://simurg.example/")
    h = _h("CodeRED: Orion")
    assert reg.branded_url(h) == "https://simurg.example/codered-orion"


def test_registry_reuses_slug_for_same_url():
    h = _h("CodeRED: Orion")
    store = FakeStore({"codered-orion": h.url})
    assert LinkRegistry(store, base_url="https://b").slug_for(h) == "codered-orion"
    assert len(store.rows) == 1


def test_registry_resolves_collision_with_year():
    store = FakeStore({"codered-orion": "https://other.test"})
    assert LinkRegistry(store, base_url="https://b").slug_for(_h("CodeRED: Orion")) == "codered-orion-2026"


def test_registry_falls_back_to_organizer_url_and_disables_on_db_error():
    class Broken:
        calls = 0

        def find_by_url(self, url):
            Broken.calls += 1
            raise RuntimeError("neon asleep")

        def try_insert(self, *a):
            raise AssertionError("unreachable")

    reg = LinkRegistry(Broken(), base_url="https://b")
    h1, h2 = _h("One"), _h("Two")
    assert reg.branded_url(h1) == h1.url
    assert reg.branded_url(h2) == h2.url
    assert Broken.calls == 1  # one failure disables it for the run


def test_registry_without_store_returns_organizer_url():
    h = _h("One")
    assert LinkRegistry(None).branded_url(h) == h.url


def test_public_url_joins_cleanly():
    assert public_url("x", "https://a.vercel.app/") == "https://a.vercel.app/x"


def test_dsn_conversion_from_sqlalchemy_url():
    assert _to_libpq_dsn("postgresql+asyncpg://u:p@h/db?ssl=require") == "postgresql://u:p@h/db?sslmode=require"
    assert _to_libpq_dsn("postgres://u:p@h/db?sslmode=require") == "postgresql://u:p@h/db?sslmode=require"


def test_posted_urls_uses_store_and_fails_closed():
    class Store(FakeStore):
        def existing_urls(self, urls):
            return {u for u in urls if u in self.rows.values()}

    store = Store({"a": "https://x.test/a"})
    reg = LinkRegistry(store, base_url="https://b")
    assert reg.posted_urls(["https://x.test/a", "https://x.test/b"]) == {"https://x.test/a"}

    class Broken(FakeStore):
        def existing_urls(self, urls):
            raise RuntimeError("down")

    assert LinkRegistry(Broken(), base_url="https://b").posted_urls(["u"]) == set()
    assert LinkRegistry(None).posted_urls(["u"]) == set()
