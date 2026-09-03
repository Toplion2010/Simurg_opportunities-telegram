"""A 0-100 relevance score combining reachability ("coolness") and profile fit.

Used by both collector pipelines (Telegram via src/processor/pipeline.py, web
catalogs via src/collector/web/to_dto.py) so an opportunity's rank in the
admin queue -- and now the daily digest's auto-approve/review split -- means
the same thing regardless of where it came from. Lives in core/ rather than
processor/ or collector/web/ for the same reason geo.py does: both siblings
need it, and neither should import from the other.

Replaces an earlier 1-10 table (reachability tier x fit tier, 16 cells) that
was too coarse once the job became "pick the real top 5 out of hundreds of
pending rows a day" rather than just "sort a queue a human browses by hand".
Both axes are now continuous point totals instead of table lookups, so ties
are rare.

  COOLNESS (0-60) -- can a Kazakh student actually get there, and how good
  is the deal. Built on the same reachability tiers as before (R1..R4, see
  reachability_tier()), plus a continuous bonus for how strong the signal is
  within that tier:

    R1 (floor 0)   in-person, priced, unfunded, not Kazakhstan-local -- or
                   the citizenship/residency bar. No bonus; this is the
                   score floor.
    R2 (floor 15)  free/cheap in-person with no funding language, or
                   genuinely unknown online-ness AND cost. Bonus (0-10)
                   scales with how far under WEB_SMALL_FEE_USD the (known)
                   cost is; an unknown cost gets a flat mid-range bonus.
    R3 (floor 30)  partial funding, not Kazakhstan-local. Bonus (0-15) scales
                   with how many distinct funding signals were found
                   (find_funding()) -- "scholarship" alone reads weaker than
                   "scholarship, financial aid, stipend" together.
    R4 (floor 45)  online, OR fully funded, OR Kazakhstan-local and
                   funded/cheap. Bonus is at its max (+15) for online or full
                   funding, slightly less (+12) for the KZ-local case, since
                   a local program still costs the price of a bus ticket at
                   worst.

  The tier ranges never overlap (R1=0, R2=15-25, R3=37-45, R4=57-60), so
  coolness alone already orders every reachability outcome correctly.

  FIT (0-40) -- how well the opportunity matches THIS profile specifically:
  competitive programmer (Codeforces, ICPC finalist), AI/ML builder and
  researcher (computer vision, NLP), founder, full-stack engineer. Chess,
  pure math olympiads and sports are real CV lines but are NOT this
  profile's focus -- they score as off-profile (0) regardless of what else
  co-occurs in the same text. Four tiers, each a fixed base plus up to +6
  for multiple distinct signals at the winning tier:

    4 (base 34)  AI/ML, competitive programming, hackathons, founder/startup,
                 and CS/tech-context-gated research programs.
    3 (base 22)  adjacent software engineering (web/mobile/full-stack, data
                 science/engineering, open source).
    2 (base 10)  loosely related -- STEM, "tech program", generic
                 innovation/product language with no CS/AI keyword alongside.
    1 (base 0)   everything else, explicitly including chess, math olympiad
                 and sports terms. A bare "competition" is not enough signal
                 by itself to reach tier 4 -- only the specific CS/AI/
                 competitive-programming terms above do.

`score()` returns COOLNESS + FIT (0-100) and a reason naming both
components' rationale, auditable straight off a queue card or a daily digest
push, e.g.:

    "cool 51/60 (fully funded) + fit 34/40 (core: computer vision, hackathon)"
"""
import re

# --- funding & citizenship regexes ---------------------------------------
# Owned here; src/collector/web/filters.py imports _CITIZENSHIP_RE and
# find_funding back rather than redefining them, so the admission gate and
# the score always agree on what "funded" and "citizens only" mean.

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

# Any funding mention at all -- covers both partial and full coverage;
# _FULL_FUNDING_PHRASES_RE below narrows to the subset that also covers
# travel and lodging.
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
# reachable item as unaffordable -- worse than not knowing at all.
_NON_USD_MARKER_RE = re.compile(
    r"kzt|тенге|₸|rub|руб|₽|eur|€|gbp|£|\bkr\b", re.IGNORECASE
)


def infer_cost_amount(cost_text: str | None) -> float | None:
    """Best-effort numeric cost from a free-text field like "Free", "$50",
    "Paid", "$1,200/session". A messy string that does not parse, or a
    number next to a non-USD currency marker, returns None (unknown) rather
    than a wrong number -- the safe direction for scoring.
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


# --- coolness (0-60) --------------------------------------------------------

_REACH_FLOOR = {R1: 0, R2: 15, R3: 30, R4: 45}
_REACH_BONUS_MAX = 15


def coolness_score(
    is_online: bool | None,
    cost_amount: float | None,
    location: str | None,
    text: str,
    small_fee_usd: float = 50.0,
) -> tuple[int, str]:
    """(score 0-60, reason). Continuous version of reachability_tier(): the
    tier sets a floor, a same-tier bonus separates a strong signal (fully
    funded, $0 fee) from a weak one (one funding phrase, $45 of a $50 cap).
    """
    text = text or ""
    tier, label = reachability_tier(is_online, cost_amount, location, text, small_fee_usd)
    floor = _REACH_FLOOR[tier]

    if tier == R1:
        return (floor, label)

    if tier == R4:
        bonus = _REACH_BONUS_MAX if label in ("online", "fully funded") else 12
    elif tier == R3:
        signals = find_funding(text)
        bonus = min(_REACH_BONUS_MAX, 5 + 2 * len(signals))
    else:  # R2
        if cost_amount is not None and small_fee_usd > 0:
            cheapness = max(0.0, 1 - min(cost_amount, small_fee_usd) / small_fee_usd)
            bonus = round(10 * cheapness)
        else:
            bonus = 5  # unknown cost: a flat, middling bonus, not a guess

    return (floor + bonus, label)


# --- fit (0-40) --------------------------------------------------------

# Profile: competitive programmer (Codeforces, ICPC finalist), AI/ML builder
# and researcher (computer vision, NLP, forensics), founder, full-stack
# engineer. Chess, pure math olympiads and sports are real CV lines but are
# NOT this profile's focus -- they must read as off-profile even when they
# share text with something that genuinely is.
_TIER4_KEYWORD_RE = re.compile(
    r"machine learning|artificial intelligence|computer vision|\bnlp\b|"
    r"deep learning|neural network|\bllm\b|generative ai|ai research|\bai\b|"
    r"\bicpc\b|\bioi\b|codeforces|competitive programming|algorithmic contest|"
    r"\balgorithm\b|"
    r"\bhackathons?\b|\bhack\b|"
    r"\bstartups?\b|\bfounders?\b|entrepreneurship|\baccelerators?\b|\bincubators?\b",
    re.IGNORECASE,
)
# Research only counts as core fit alongside a CS/tech context -- "research
# program" alone says nothing about the field it's in.
_RESEARCH_PHRASE_RE = re.compile(
    r"research (?:intern(?:ship)?|program(?:me)?|fellowship)", re.IGNORECASE
)
_TECH_CONTEXT_RE = re.compile(
    r"computer science|\bsoftware\b|\btechnology\b|\btech\b|\bengineering\b|"
    r"informatics|programming|\bcs\b|\bdata\b|\bcoding\b|artificial intelligence|"
    r"machine learning|\bai\b",
    re.IGNORECASE,
)

_TIER3_KEYWORD_RE = re.compile(
    r"software engineer(?:ing)?|web development|full[- ]stack|mobile development|"
    r"data science|data engineering|open source",
    re.IGNORECASE,
)

_TIER2_KEYWORD_RE = re.compile(
    r"\bstem\b|tech(?:nology)? program|\binnovation\b|\bproduct\b",
    re.IGNORECASE,
)

# Explicit off-profile terms, purely so a real "why is this 0" reason exists
# instead of the generic no-match fallback -- functionally both are base 0.
_TIER1_KEYWORD_RE = re.compile(
    r"\bchess\b|math(?:ematical)? olympiad|\bsports?\b|\bathlet\w*|\bfootball\b|"
    r"\bbasketball\b|\btennis\b|\bswimming\b",
    re.IGNORECASE,
)

_TIER_BASE = {4: 34, 3: 22, 2: 10, 1: 0}
_FIT_BONUS_MAX = 6
_MAX_LISTED_MATCHES = 3


def fit_tier(text: str) -> tuple[int, str]:
    """(tier 1-4, reason). Highest-scoring signal present, not the first."""
    text = text or ""

    match4 = _TIER4_KEYWORD_RE.search(text)
    if match4:
        return (4, match4.group(0).strip().lower())

    research_match = _RESEARCH_PHRASE_RE.search(text)
    if research_match and _TECH_CONTEXT_RE.search(text):
        return (4, research_match.group(0).strip().lower())

    match3 = _TIER3_KEYWORD_RE.search(text)
    if match3:
        return (3, match3.group(0).strip().lower())

    match2 = _TIER2_KEYWORD_RE.search(text)
    if match2:
        return (2, match2.group(0).strip().lower())

    match1 = _TIER1_KEYWORD_RE.search(text)
    if match1:
        return (1, f"off-profile: {match1.group(0).strip().lower()}")

    return (1, "no profile keywords matched")


def fit_score(text: str) -> tuple[int, str]:
    """(score 0-40, reason). Fixed tier base + up to +6 for multiple distinct
    signals at the winning tier -- a listing naming several core-fit
    keywords outranks one that barely qualifies."""
    text = text or ""
    tier, label = fit_tier(text)
    base = _TIER_BASE[tier]

    if tier == 4:
        matches = {m.group(0).strip().lower() for m in _TIER4_KEYWORD_RE.finditer(text)}
        research_match = _RESEARCH_PHRASE_RE.search(text)
        if research_match and _TECH_CONTEXT_RE.search(text):
            matches.add(research_match.group(0).strip().lower())
    elif tier == 3:
        matches = {m.group(0).strip().lower() for m in _TIER3_KEYWORD_RE.finditer(text)}
    elif tier == 2:
        matches = {m.group(0).strip().lower() for m in _TIER2_KEYWORD_RE.finditer(text)}
    else:
        matches = set()

    bonus = min(_FIT_BONUS_MAX, 2 * max(0, len(matches) - 1))
    value = base + bonus

    if matches:
        shown = sorted(matches)[:_MAX_LISTED_MATCHES]
        suffix = ", ..." if len(matches) > _MAX_LISTED_MATCHES else ""
        prefix = {4: "core", 3: "adjacent", 2: "general"}[tier]
        reason = f"{prefix}: {', '.join(shown)}{suffix}"
    else:
        reason = label

    return (value, reason)


# --- combined score ------------------------------------------------------

# Opportunity.relevance_reason is a String(120) column. Assignment on an
# already-constructed OpportunityDTO (src/processor/pipeline.py's Telegram
# path) bypasses pydantic validators entirely, so length has to be enforced
# here to be safe for both callers.
_MAX_REASON_LEN = 120


def score(
    is_online: bool | None,
    cost_amount: float | None,
    location: str | None,
    text: str,
    small_fee_usd: float = 50.0,
) -> tuple[int, str]:
    """(score 0-100, reason). `text` should include title, description and
    eligibility at minimum -- everywhere funding, citizenship and fit
    keywords might appear."""
    text = text or ""
    cool, cool_label = coolness_score(is_online, cost_amount, location, text, small_fee_usd)
    fit, fit_label = fit_score(text)
    value = cool + fit
    reason = f"cool {cool}/60 ({cool_label}) + fit {fit}/40 ({fit_label})"
    if len(reason) > _MAX_REASON_LEN:
        reason = reason[: _MAX_REASON_LEN - 3] + "..."
    return (value, reason)
