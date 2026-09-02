r"""Does a free-text location name somewhere in Kazakhstan?

Used by the publisher to route KZ hackathons into the dedicated hackathons
channel *in addition to* their normal audience channels (see
``src/publisher/sender.py``), and by ``scripts.diagnose_approvals`` to measure
how often the extractor's ``location`` field carries a usable KZ signal at all.

Lives in ``core/`` rather than ``publisher/`` so that diagnostic can import it
without pulling in aiogram.

The public entry point returns the *matched token* rather than a bool, so a
production misroute names the token that caused it and the diagnostic can print
``location -> token``.

Matching
--------
Both the input and every token pass through :func:`normalize`::

    casefold  ->  fold Kazakh-only letters to their Russian neighbours
              ->  NFD  ->  drop combining marks

That collapses ``Karagandy`` / ``Караганда`` / ``Қарағанды`` toward one token
and quietly handles ``Oskemen`` and ``Turkistan``. Two consequences the token
lists must respect:

* the fold turns ``Қазақстан`` into a *к*, so both ``казахстан`` and
  ``казакстан`` are listed;
* NFD decomposes ``й`` into ``и`` plus a combining breve, which is then
  dropped, so no Cyrillic token may contain ``й``. Write the stem ``костана``,
  never ``костанай``. ``tests/test_geo.py`` pins this.

Tokens come in two tiers, matched with lookarounds rather than ``\b`` so the
guard behaves identically around a hyphen (``nur-sultan``):

* **exact** -- ``(?<!\w)token(?!\w)``
* **stem**  -- ``(?<!\w)token`` only, because Russian declines
  (``Астана`` / ``Астаны`` / ``Астане``)

Country tokens are tried before city tokens, so "Almaty, Kazakhstan" reports
``kazakh`` rather than whichever token happens to sit leftmost.

Deliberately excluded
---------------------
Every row here is pinned as a negative test.

=========================  =====================================================
``oral`` / ``орал``        Uralsk in Kazakh, but also "oral presentation", and
                           ``орал`` is an ordinary Russian verb. Use
                           ``uralsk`` / ``уральск``.
``ural`` / ``урал``        The Urals are in **Russia** (Ural Federal University).
                           This is also why ``уральск`` is exact-only: as a
                           stem it matched "Уральский федеральный университет".
``семей``                  Semey in Russian, and also the genitive plural of
                           ``семья``: "для семей" means "for families". The
                           Latin ``semey`` has no such homograph and is kept.
``kaz`` as a stem          Swallows **Kazan**. Only the full ``kazakh`` /
                           ``kazakst`` stems are safe.
``kzn``                    Kazan's code. ``kz`` survives only with both guards.
``petropavlovsk``          Petropavlovsk-Kamchatsky is Russian, so ``петропавл``
                           is exact-only and matches just the Kazakh name.
any ``stan`` token         Uzbekistan / Pakistan / Kyrgyzstan / Turkmenistan,
                           the highest-volume false-positive family.
2-3 letter acronyms        ``рк``, ``nis``, ``sdu``: unbounded collision surface.
=========================  =====================================================

``turkestan`` is a knowing exception to the rule above it: the KZ city is
spelled that way, and "East Turkestan" (Xinjiang) is the one collision -- rare
enough in a hackathon location field to accept.

Rule for adding a city later: it earns a token only if it plausibly appears
*alone*. "Stepnogorsk, Kazakhstan" is already caught by the country stem.

``"Online"``, ``"Remote"``, ``"Worldwide"``, ``None`` and ``""`` all return
``None``. Format is irrelevant to this matcher rather than a signal of its own:
a global online hackathon with no KZ mention is not a KZ hackathon.
"""
import re
import unicodedata

__all__ = ["match_kazakhstan", "is_kazakhstan", "normalize", "EXACT_TOKENS", "STEM_TOKENS"]

# Kazakh-only letters folded onto their nearest Russian neighbour, so one token
# covers both spellings of a city. Applied after casefold(), hence lowercase keys.
_KAZAKH_FOLD = str.maketrans(
    {
        "ә": "а",
        "ғ": "г",
        "қ": "к",
        "ң": "н",
        "ө": "о",
        "ұ": "у",
        "ү": "у",
        "һ": "х",
        "і": "и",
    }
)


def normalize(text: str) -> str:
    """casefold -> Kazakh fold -> NFD -> strip combining marks.

    Applied to the input and to every token, so the two always meet in the same
    alphabet. Latin diacritics fall out for free here (Oskemen, Turkistan), as
    does the decomposition of ``й`` into ``и``, which is why no token may
    contain it.
    """
    folded = text.casefold().translate(_KAZAKH_FOLD)
    return "".join(
        ch for ch in unicodedata.normalize("NFD", folded) if not unicodedata.combining(ch)
    )


# --- Country -------------------------------------------------------------
# `kz` is exact-only: both guards are what keep it off Kazan's `kzn`. A bare
# `kaz` stem is deliberately absent for the same reason.
_COUNTRY_EXACT = ("kz",)
# `казакстан` is not a typo -- the fold turns the қ of `Қазақстан` into к.
_COUNTRY_STEMS = ("kazakh", "kazakst", "qazaq", "казахстан", "казакстан")

# --- Cities --------------------------------------------------------------
# Latin forms do not decline, so they are exact; Cyrillic ones mostly do, so
# they are stems. `петропавл` is the exception -- exact on purpose, so Russia's
# Петропавловск-Камчатский cannot match.
_CITY_EXACT = (
    "almaty",
    "alma-ata",
    "astana",
    "nur-sultan",
    "nursultan",
    "shymkent",
    "chimkent",
    "aktobe",
    "aqtobe",
    "atyrau",
    "aktau",
    "aqtau",
    "pavlodar",
    "semey",
    "semipalatinsk",
    "taraz",
    "oskemen",
    "ust-kamenogorsk",
    "kyzylorda",
    "qyzylorda",
    "turkestan",
    "turkistan",
    "petropavl",
    "uralsk",
    "temirtau",
    "kokshetau",
    "taldykorgan",
    "ekibastuz",
    "zhezkazgan",
    "jezkazgan",
    "zhanaozen",
    "baikonur",
    "baykonur",
    "konaev",
    "konayev",
    "balkhash",
    "актобе",
    "актау",
    "темиртау",
    "кокшетау",
    "петропавл",
    # Exact for the same reason as петропавл: the stem would swallow
    # "Уральский федеральный университет", which is in Russia.
    "уральск",
)
_CITY_STEMS = (
    # Latin, where a transliterated suffix is plausible.
    "karagand",
    "qaragand",
    "kostana",
    "qostana",
    # Cyrillic -- Russian declines, so no trailing guard.
    "алмат",
    "алма-ат",
    "астан",
    "нур-султан",
    "нурсултан",
    "шымкент",
    "чимкент",
    "караганд",
    "актюбинск",
    "атырау",
    "павлодар",
    "семипалатинск",
    "тараз",
    "оскемен",
    "усть-каменогорск",
    "костана",
    "кызылорд",
    "туркестан",
    "талдыкорган",
    "екибастуз",
    "жезказган",
    "жанаозен",
    # Байконур, spelled as it normalizes: NFD splits й into и + a combining
    # breve and the breve is dropped. Written with й it could never match.
    "баиконур",
    "конаев",
    "балхаш",
)

#: Every token matched with a guard on both sides. Exposed for the hygiene tests.
EXACT_TOKENS = _COUNTRY_EXACT + _CITY_EXACT
#: Every token matched with a leading guard only, i.e. as a prefix.
STEM_TOKENS = _COUNTRY_STEMS + _CITY_STEMS


def _build(exact: tuple[str, ...], stems: tuple[str, ...]) -> "re.Pattern[str]":
    # Longest token first, so a string matching two tokens reports the more
    # specific one. A stem alternative is the bare token and an exact
    # alternative is the token plus a zero-width lookahead, so group(0) is
    # always exactly the token that matched -- which is what the public
    # functions return.
    pairs = [(t, re.escape(t) + r"(?!\w)") for t in exact] + [(t, re.escape(t)) for t in stems]
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(alt for _, alt in pairs) + r")")


_COUNTRY_RE = _build(_COUNTRY_EXACT, _COUNTRY_STEMS)
_CITY_RE = _build(_CITY_EXACT, _CITY_STEMS)


def match_kazakhstan(text: str | None) -> str | None:
    """Return the token proving `text` names somewhere in Kazakhstan, else None.

    The token, not a bool, so a misroute in production is debuggable from the
    log line alone.
    """
    if not text:
        return None
    normalized = normalize(text)
    for pattern in (_COUNTRY_RE, _CITY_RE):
        found = pattern.search(normalized)
        if found:
            return found.group(0)
    return None


def is_kazakhstan(text: str | None) -> bool:
    return match_kazakhstan(text) is not None
