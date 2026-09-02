import pytest

from src.core.geo import EXACT_TOKENS, STEM_TOKENS, is_kazakhstan, match_kazakhstan, normalize


@pytest.mark.parametrize(
    "text",
    [
        # Country, every spelling the fold has to survive.
        "Kazakhstan",
        "kazakhstan",
        "Kazakstan",
        "Qazaqstan",
        "Казахстан",
        "Қазақстан",
        "в Казахстане",
        "Almaty, KZ",
        "Astana, Kazakhstan",
        "https://hackathon.kz",
        # Cities, Latin.
        "Almaty",
        "Alma-Ata",
        "Astana",
        "Nur-Sultan",
        "Shymkent",
        "Karaganda",
        "Karagandy",
        "Aktobe",
        "Atyrau",
        "Aktau",
        "Pavlodar",
        "Semey",
        "Taraz",
        "Kostanay",
        "Kyzylorda",
        "Petropavl",
        "Uralsk",
        "Ekibastuz",
        "Baikonur",
        "Balkhash",
        # Cities, Cyrillic, including declined forms (the reason for stems).
        "Алматы",
        "Астана",
        "в Астане",
        "Астаны",
        "Шымкент",
        "Караганда",
        "Қарағанды",
        "Костанай",
        "из Костаная",
        "Уральск",
        "Актобе",
        "Байконур",
        # Diacritics, folded away by NFD.
        "Öskemen",
        "Türkistan",
        # Mixed, realistic location strings.
        "Almaty, Kazakhstan",
        "Онлайн + офлайн, Алматы",
        "Astana Hub, Astana",
        "hybrid — Shymkent and online",
    ],
)
def test_matches(text):
    assert match_kazakhstan(text) is not None
    assert is_kazakhstan(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # The -stan family, the highest-volume false-positive risk.
        "Uzbekistan",
        "Tashkent, Uzbekistan",
        "Pakistan",
        "Islamabad, Pakistan",
        "Kyrgyzstan",
        "Bishkek, Kyrgyzstan",
        "Turkmenistan",
        "Tajikistan",
        "Узбекистан",
        "Кыргызстан",
        "Пакистан",
        "Таджикистан",
        # Kazan, which a `kaz` stem or a loose `kz` would swallow.
        "Kazan",
        "Kazan, Russia",
        "Kazan Federal University",
        "kzn",
        "Казань",
        # The Urals are Russian.
        "Ural",
        "Ural Federal University",
        "Урал",
        "Уральский федеральный университет",
        # Uralsk's Kazakh name collides with ordinary words in both languages.
        "oral presentation",
        "Oral round",
        "он орал на всю улицу",
        # Semey's Russian name is the genitive plural of "family".
        "фестиваль для семей",
        "поддержка молодых семей",
        # Russia's Petropavlovsk, which is why петропавл is exact-only.
        "Petropavlovsk-Kamchatsky",
        "Петропавловск-Камчатский",
        # Assorted non-KZ places that share a prefix or a look.
        "Berlin, Germany",
        "Baku, Azerbaijan",
        "Istanbul",
        "Стамбул",
        "Moscow",
        "Москва",
        "Kosovo",
        "Astoria, New York",
    ],
)
def test_false_positive_traps(text):
    assert match_kazakhstan(text) is None
    assert is_kazakhstan(text) is False


@pytest.mark.parametrize("text", ["Online", "online", "Remote", "Worldwide", "Virtual", "", None])
def test_format_is_not_a_signal(text):
    """A global online hackathon with no KZ mention is not a KZ hackathon."""
    assert match_kazakhstan(text) is None
    assert is_kazakhstan(text) is False


def test_returns_the_matched_token_not_a_bool():
    # The token is what makes a production misroute debuggable from the log.
    assert match_kazakhstan("Almaty") == "almaty"
    assert match_kazakhstan("Kazakhstan") == "kazakh"
    # Country beats city, so the most reassuring token is the one reported.
    assert match_kazakhstan("Almaty, Kazakhstan") == "kazakh"
    # The token is returned normalized, i.e. exactly as it appears in the list.
    assert match_kazakhstan("Қарағанды") == "караганд"


def test_online_plus_a_kz_mention_still_matches():
    # "Online or offline" means format is irrelevant, not that online excludes.
    assert match_kazakhstan("Online, Kazakhstan") is not None
    assert match_kazakhstan("Remote (Almaty-based team)") is not None


@pytest.mark.parametrize("token", EXACT_TOKENS + STEM_TOKENS)
def test_every_token_survives_its_own_normalization(token):
    # A token that normalizes to something else can never match, because the
    # input is normalized before the regex runs.
    assert normalize(token) == token
    assert match_kazakhstan(token) is not None


@pytest.mark.parametrize("token", EXACT_TOKENS + STEM_TOKENS)
def test_no_token_contains_short_i(token):
    # NFD decomposes й into и + a combining breve and the breve is dropped, so
    # a token written with й is silently dead. Байконур is spelled баиконур.
    assert "й" not in token


@pytest.mark.parametrize("tier", [EXACT_TOKENS, STEM_TOKENS], ids=["exact", "stem"])
def test_no_token_is_a_substring_of_another_in_its_tier(tier):
    # A redundant token makes the reported match arbitrary and hides which
    # entry is actually earning its place.
    assert [(a, b) for a in tier for b in tier if a != b and a in b] == []
