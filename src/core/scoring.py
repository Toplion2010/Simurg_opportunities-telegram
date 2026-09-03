"""A 1-10 relevance score combining reachability and profile fit.

Used by both collector pipelines (Telegram via src/processor/pipeline.py, web
catalogs via src/collector/web/to_dto.py) so an opportunity's rank in the
admin queue means the same thing regardless of where it came from. Lives in
core/ rather than processor/ or collector/web/ for the same reason geo.py
does: both siblings need it, and neither should import from the other.

Two axes, kept genuinely independent:

  REACHABILITY -- can a Kazakh student actually get there. Four tiers,
  worst-first:

    R1  in-person, priced, unfunded, not Kazakhstan-local. Normally
        unreachable for web items (collector.web.filters.admits() already
        rejects this combination before scoring ever runs) but real for
        Telegram, which has no such gate.
    R2  in-person, free or a small fee, no funding language at all -- the
        student would cover travel and lodging entirely themselves. Also the
        conservative default when online-ness and cost are both genuinely
        unknown: unknown must not be scored as though it were confirmed
        online, the way the admission GATE is allowed to (that gate optimizes
        for "worth a human looking at"; this optimizes for "how good is it").
    R3  in-person, PARTIAL funding -- a funding term matches (scholarship,
        financial aid, fee waiver, stipend...) but not full coverage, and the
        opportunity is not itself located in Kazakhstan.
    R4  online (or hybrid with an online track), OR in-person with FULL
        funding (travel and lodging both covered -- "fully funded", "all
        expenses paid", or a travel-term and a lodging-term both present), OR
        in-person AND located in Kazakhstan AND (funded or free/cheap) --
        local means there is no flight to fund in the first place, so partial
        funding that excludes travel is moot.

  A citizenship/residency bar (the same regex the admission gate uses) clamps
  reachability to R1 rather than causing a rejection -- consistent with
  relevance being sort-only, never a reject signal (see queue.py's own
  "Triage fields ... never auto-reject" comment). This is the first time that
  bar means anything for Telegram-sourced items at all, since admits() only
  ever ran against web items.

  FIT -- the extractor's own four bands, unchanged wording: Core(4) /
  Adjacent-STEM-business(3) / General-with-real-content(2) / Off-profile(1).
  Keyword-derived for BOTH sources (no LLM call) so an item's fit score means
  the same thing whether it came from Telegram or a scraped catalog.

The two combine through a small monotonic table, not a formula -- every score
1-10 appears in the table below at least once, and each cell is individually
auditable:

           Core  Adjacent  General  Off-profile
    R4      10      9         7         6
    R3       8      6         5         3
    R2       5      4         3         2
    R1       3      2         2         1
"""
import re

# --- funding & citizenship regexes ---------------------------------------
# Owned here now; src/collector/web/filters.py imports _CITIZENSHIP_RE and
# find_funding back rather than redefining them, so the admission gate and
# the score always agree on what "funded" and "citizens only" mean.

# A hard legal bar, not a preference. The NSF-REU family ("US citizens,
# nationals, or permanent residents") is the single highest-volume exclusion
# in the web catalogs, and no amount of funding lifts it.
_CITIZENSHIP_PATTERNS = [
    r"u\.?\s?s\.?\s+citizens?",
    r"united states citizens?",
    r"american citizens?",
    r"citizens? of the united states",
    r"permanent residents?",
    r"green\s?card",
    r"domestic students? only",
    r"must be a (?:us|u\.s\.|united states) (?:citizen|resident)",
    r"must (?:be|currently be) (?:a )?resid\w+ (?:of|in) (?!kazakh)",
    r"open (?:only )?to (?:us|u\.s\.|united states|american) ",
    r"restricted to (?:us|u\.s\.|united states|american) ",
    r"(?:enrolled|attending) (?:in |at )?(?:a )?(?:us|u\.s\.|american) (?:high )?schools?",
]
_CITIZENSHIP_RE = re.compile("|".join(_CITIZENSHIP_PATTERNS), re.IGNORECASE)

# Any funding mention at all -- covers both partial (R3) and full (R4)
# coverage; _FULL_FUNDING_PHRASES_RE below narrows to the subset that also
# covers travel and lodging.
_FUNDING_PATTERNS = [
    r"scholarship",
    r"financial aid",
    r"need[- ]based",
    r"fee waiver",
    r"waivers? available",
    r"stipend",
    r"fully funded",
    r"full funding",
    r"travel grant",
    r"grant(?:s)? available",
    r"bursary",
    r"free of charge",
    r"no cost",
    r"tuition[- ]free",
    r"sliding scale",
    r"pay what you can",
    r"бесплат",
    r"стипенди",
    r"грант",
]
_FUNDING_RE = re.compile("|".join(_FUNDING_PATTERNS), re.IGNORECASE)

# The subset of funding language that specifically claims travel AND lodging
# are covered -- the two costs that make an in-person program actually
# unreachable from Kazakhstan. "Scholarship" alone does not imply this; a
# scholarship that only waives tuition still leaves a plane ticket unpaid.
_FULL_FUNDING_PHRASES_RE = re.compile(
    r"fully funded|full funding|all[- ]expenses[- ]paid|all expenses paid",
    re.IGNORECASE,
)
_TRAVEL_TERM_RE = re.compile(r"\btravel\b|\bflights?\b|\bairfare\b", re.IGNORECASE)
_LODGING_TERM_RE = re.compile(r"\baccommodation\b|\blodging\b|\bhousing\b", re.IGNORECASE)


def find_funding(text: str | None) -> list[str]:
    """Distinct funding signals present in `text`, lowercased and deduped.

    Split out from the admission gate because the web catalogs themselves are
    nearly prose-free: across 45 real ExtracurricularHub listings, ZERO
    contained any funding language, so this can only fire against the
    OFFICIAL page's text, not the catalog record. See
    collector/web/fetcher._funding_on_official_page.
    """
    if not text:
        return []
    return sorted({m.group(0).lower() for m in _FUNDING_RE.finditer(text)})


def _is_fully_funded(text: str) -> bool:
    if _FULL_FUNDING_PHRASES_RE.search(text):
        return True
    return bool(_TRAVEL_TERM_RE.search(text) and _LODGING_TERM_RE.search(text))


# --- reachability ----------------------------------------------------------

_ONLINE_MARKERS_RE = re.compile(
    r"\bonline\b|\bremote\b|\bvirtual\b|\bhybrid\b|\bworldwide\b|\banywhere\b",
    re.IGNORECASE,
)

R1, R2, R3, R4 = 1, 2, 3, 4
_REACH_LABELS = {
    R1: "unfunded in-person",
    R2: "cheap in-person, no funding",
    R3: "partial funding",
    R4: "online/funded/local",
}


def infer_is_online(location: str | None) -> bool | None:
    """Best-effort online-ness from a free-text location string.

    Used for Telegram-sourced items, which have no structured is_online field
    the way a scraped WebItem does -- see the module docstring's note on R2
    being the safe default for genuinely unknown input.
    """
    if not location or not location.strip():
        return None
    if _ONLINE_MARKERS_RE.search(location):
        return True
    return False


_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
_FREE_RE = re.compile(r"\bfree\b(?!\s+of\s+charge)|\bfree\s+of\s+charge\b", re.IGNORECASE)
_USD_MARKER_RE = re.compile(r"\$|usd|dollars?", re.IGNORECASE)
# A number next to one of these means the amount is almost certainly NOT USD.
# The Kazakhstan-local case is exactly why this matters: "5000 KZT" is roughly
# $10, but a currency-blind parse reads it as $5000 and scores a cheap, local,
# reachable item as unaffordable -- worse than not knowing at all, since
# reachability_tier's small_fee_usd comparison assumes every cost_amount is in
# dollars.
_NON_USD_MARKER_RE = re.compile(
    r"kzt|тенге|₸|rub|руб|₽|eur|€|gbp|£|\bkr\b", re.IGNORECASE
)


def infer_cost_amount(cost_text: str | None) -> float | None:
    """Best-effort numeric cost from a free-text field like "Free", "$50",
    "Paid", "$1,200/session". Lower fidelity than a scraped source's real
    cost_amount by design -- a messy string that does not parse returns None
    (unknown), which is the safe direction for scoring, never the expensive
    direction. A number found next to a non-USD currency marker ALSO returns
    None rather than a wrong number -- see the Kazakhstan note above.
    """
    if not cost_text or not cost_text.strip():
        return None
    if _FREE_RE.search(cost_text):
        return 0.0
    if _NON_USD_MARKER_RE.search(cost_text) and not _USD_MARKER_RE.search(cost_text):
        return None
    match = _AMOUNT_RE.search(cost_text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def reachability_tier(
    is_online: bool | None,
    cost_amount: float | None,
    location: str | None,
    text: str,
    small_fee_usd: float = 50.0,
) -> tuple[int, str]:
    """(tier, label). `text` should be everything free-text available
    (title + description + eligibility, at minimum) -- it is where funding
    and citizenship language lives."""
    if _CITIZENSHIP_RE.search(text):
        return (R1, "citizenship/residency bar")

    is_local = False
    try:
        from src.core.geo import is_kazakhstan

        is_local = is_kazakhstan(location)
    except Exception:
        is_local = False

    fully_funded = _is_fully_funded(text)
    any_funding = bool(_FUNDING_RE.search(text))
    is_free_or_cheap = cost_amount is None or cost_amount <= small_fee_usd

    if is_online is True:
        return (R4, "online")
    if fully_funded:
        return (R4, "fully funded")
    if is_local and (any_funding or is_free_or_cheap):
        return (R4, "in Kazakhstan, no flight needed")

    # Genuinely unknown format AND unknown/cheap cost: conservative default,
    # not an assumption of reachability. Checked AFTER the unconditional
    # online/funded/local checks above, so a known-good signal always wins
    # over uncertainty.
    if is_online is None and cost_amount is None:
        return (R2, "format and cost unknown")

    if is_online is False and any_funding and not fully_funded:
        return (R3, "partial funding")

    if is_online is not False and is_free_or_cheap:
        # is_online is None here (True already returned above): unknown
        # format, but cheap/free, so no travel-affordability question either.
        return (R2, "cheap, format unknown")

    if is_online is False and is_free_or_cheap:
        return (R2, _REACH_LABELS[R2])

    return (R1, _REACH_LABELS[R1])


# --- fit ---------------------------------------------------------------

# Profile fit, using the SAME 1-5 language the extractor prompt used to
# define directly (now computed here instead of asked of the LLM -- see
# src/processor/extractor.py's removal of the relevance field):
#   4 = core fit, 3 = adjacent STEM/business, 2 = general with real content,
#   1 = off-profile.
_FIT_TERMS: list[tuple[int, str]] = [
    (4, r"computer science|artificial intelligence|\bai\b|machine learning|"
        r"cybersecurity|robotic|hackathon|programming|software|data science|"
        r"\bhacking\b|informatics|\bcoding\b|competitive programming|"
        # math misses real program names -- Mathcounts, Mathletes, MathWorks
        # -- and the repair path often has only a title to go on. Prefix
        # match, minus the given-name forms.
        r"\bmath(?!ew|ias)\w*|olympiad|entrepreneur|startup|\bbusiness\b"),
    (3, r"engineering|physics|aerospace|technology|\bstem\b|biotech|"
        r"synthetic biology|neuroscience|science research|\binnovation\b"),
    (2, r"\bscience\b|biology|chemistry|medicine|biomedic|environmental|"
        r"marine|geography|psychology|\bgeneral\b|economics|finance|"
        r"writing|debate|model un|journalism|policy|history|philosoph|"
        r"leadership|language"),
    (1, r"\bart\b|\barts\b|music|theat|dance|sport|athlet|film|photograph|choir"),
]
_FIT_RULES = [(s, re.compile(p, re.IGNORECASE)) for s, p in _FIT_TERMS]

# Nothing matched. 2 is "general with real content", the honest reading of a
# listing whose subject we could not identify -- still above genuine
# off-profile.
_DEFAULT_FIT = 2
_DEFAULT_FIT_REASON = "no profile keywords matched"


def fit_tier(text: str) -> tuple[int, str]:
    """(tier 1-4, reason). Takes the HIGHEST-scoring signal present, not the
    first: a "Robotics and Art Camp" is a robotics opportunity that also does
    art, not an art one."""
    best: tuple[int, str] | None = None
    for tier, pattern in _FIT_RULES:
        match = pattern.search(text)
        if match and (best is None or tier > best[0]):
            best = (tier, match.group(0).strip().lower())
    if best is None:
        return (_DEFAULT_FIT, _DEFAULT_FIT_REASON)
    return best


# --- combined score ------------------------------------------------------

_SCORE_TABLE: dict[tuple[int, int], int] = {
    (R4, 4): 10, (R4, 3): 9, (R4, 2): 7, (R4, 1): 6,
    (R3, 4): 8,  (R3, 3): 6, (R3, 2): 5, (R3, 1): 3,
    (R2, 4): 5,  (R2, 3): 4, (R2, 2): 3, (R2, 1): 2,
    (R1, 4): 3,  (R1, 3): 2, (R1, 2): 2, (R1, 1): 1,
}


def score(
    is_online: bool | None,
    cost_amount: float | None,
    location: str | None,
    text: str,
    small_fee_usd: float = 50.0,
) -> tuple[int, str]:
    """(score 1-10, reason). `text` should include title, description and
    eligibility at minimum -- everywhere funding, citizenship and fit
    keywords might appear."""
    text = text or ""
    reach, reach_label = reachability_tier(
        is_online, cost_amount, location, text, small_fee_usd
    )
    fit, fit_label = fit_tier(text)
    value = _SCORE_TABLE[(reach, fit)]
    return (value, f"{reach_label} + keyword: {fit_label}")
