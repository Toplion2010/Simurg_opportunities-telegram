"""A 0-100 relevance score across six axes: affordability, attendance-ability,
selectivity, prestige/brand, topic fit, and output value.

Used by both collector pipelines (Telegram via src/processor/pipeline.py, web
catalogs via src/collector/web/to_dto.py) so an opportunity's rank in the
admin queue -- and the daily digest's auto-approve/review split -- means the
same thing regardless of where it came from. Lives in core/ rather than
processor/ or collector/web/ for the same reason geo.py does: both siblings
need it, and neither should import from the other.

v3 of this scorer. v1 was a 1-10 table (reachability tier x fit tier); v2
combined coolness (0-40) + fit (0-40) + prestige (0-20) as continuous point
totals. This version splits coolness's two conflated ideas -- "is it
affordable" and "can a Kazakhstani student actually get there" -- into their
own axes, and splits prestige's bundled "selective" and "brand name" and
"has real output" signals into three:

  AFFORDABILITY (0-25) -- cost and funding language, independent of format
  or location. Fully funded tops the scale; partial funding scales with how
  many distinct funding signals are present (find_funding()); an unfunded
  but cheap/free program scales with how far under small_fee_usd the cost
  is; an unfunded, priced program with no funding language scores 0; a
  genuinely unknown cost gets a flat, middling value rather than a guess.

  ATTENDANCE-ABILITY (0-25) -- can a Kazakhstani student actually attend,
  independent of cost. Online format is unconditionally the max (no travel
  question at all). A Kazakhstan-local in-person program is nearly as good
  (worst case, a bus ticket). An unknown format gets a flat, middling value.
  An in-person program outside Kazakhstan needs real international travel
  regardless of how it's funded -- that's Affordability's problem, not this
  axis's -- so it scores 0 here even if fully paid for.

  Citizenship/residency-bar clamp: zeroes ONLY Affordability and
  Attendance-ability (an opportunity you're legally barred from is neither
  affordable nor attendable) -- it never zeroes Selectivity, Prestige, Topic
  fit, Output value, or the total. A citizenship-barred MIT program still
  surfaces in the admin queue, low-ranked on affordability/attendance-ability
  alone but with everything else intact, rather than vanishing silently.

  SELECTIVITY (0-5) -- explicit acceptance-rate/cap language (max), a
  flagship institution's name alone as a smaller floor even with no number,
  or vague selectivity language ("highly selective") with no number at all
  as the weakest signal.

  PRESTIGE / BRAND (0-20) -- a flagship institution/org match (see
  _FLAGSHIP_INSTITUTIONS), or a weaker generic "there is clearly some
  organization involved" marker (_ORG_MARKER_RE) when no flagship name
  appears. Deliberately does not re-score the acceptance-rate/cap numbers
  Selectivity already covers.

  TOPIC FIT (0-15) -- match to THIS profile specifically: competitive
  programmer (Codeforces, ICPC finalist), AI/ML builder and researcher,
  founder, full-stack engineer. Chess, pure math olympiads and sports are
  real CV lines but are NOT this profile's focus -- they score as
  off-profile (0) regardless of what else co-occurs in the same text. Same
  four keyword tiers as before (see fit_tier()), rescaled from a 0-40 budget.

  OUTPUT VALUE (0-10) -- concrete prize/scholarship-dollar-amount language
  or publication/demo-day language (_PRIZE_PATTERNS) -- previously bundled
  into prestige, now its own axis so a program can be prestigious without a
  concrete payout, or vice versa, without the two ideas fighting for the
  same points.

`score()` returns the sum of all six axes (0-100) and a reason naming each
axis's rationale, e.g.:

    "aff 25/25 (fully funded) + att 25/25 (online) + sel 5/5 (15% acceptance) + pres 20/20 (MIT) + fit 13/15 (core: ai) + out 10/10 (cash prize)"
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


# --- shared inference helpers ---------------------------------------------

_ONLINE_MARKERS_RE = re.compile(
    r"\bonline\b|\bremote\b|\bvirtual\b|\bhybrid\b|\bworldwide\b|\banywhere\b",
    re.IGNORECASE,
)


def infer_is_online(location: str | None) -> bool | None:
    """Best-effort online-ness from a free-text location string.

    Used for Telegram-sourced items, which have no structured is_online field
    the way a scraped WebItem does.
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


def _is_local_kazakhstan(location: str | None) -> bool:
    try:
        from src.core.geo import is_kazakhstan

        return is_kazakhstan(location)
    except Exception:
        return False


# --- affordability (0-25) --------------------------------------------------

_AFFORDABILITY_MAX = 25
_AFFORDABILITY_FUNDED_BASE = 15
_AFFORDABILITY_FUNDED_BONUS_MAX = 10


def affordability_score(
    cost_amount: float | None, text: str, small_fee_usd: float = 50.0
) -> tuple[int, str]:
    """(score 0-25, reason). Cost and funding language only -- independent of
    format or location, which live in attendance_ability_score() instead."""
    text = text or ""
    if _CITIZENSHIP_RE.search(text):
        return (0, "citizenship/residency bar")

    if _is_fully_funded(text):
        return (_AFFORDABILITY_MAX, "fully funded")

    signals = find_funding(text)
    if signals:
        bonus = min(_AFFORDABILITY_FUNDED_BONUS_MAX, 2 * len(signals))
        value = min(_AFFORDABILITY_MAX, _AFFORDABILITY_FUNDED_BASE + bonus)
        return (value, f"partial funding ({signals[0]})")

    if cost_amount is not None:
        if cost_amount <= 0:
            return (20, "free")
        if cost_amount <= small_fee_usd:
            cheapness = max(0.0, 1 - cost_amount / small_fee_usd)
            return (round(10 + 10 * cheapness), f"cheap (${cost_amount:.0f})")
        return (0, f"paid (${cost_amount:.0f}), no funding")

    return (8, "cost unknown")  # unknown: a flat, middling value, not a guess


# --- attendance-ability (0-25) ---------------------------------------------

_ATTENDANCE_MAX = 25
_ATTENDANCE_LOCAL = 22
_ATTENDANCE_UNKNOWN = 10


def attendance_ability_score(
    is_online: bool | None, location: str | None, text: str
) -> tuple[int, str]:
    """(score 0-25, reason). Can a Kazakhstani student actually attend,
    independent of cost -- online is unconditionally the max, a Kazakhstan-
    local in-person program is nearly as good (worst case a bus ticket), an
    unknown format gets a flat middling value, and in-person abroad scores 0
    here regardless of funding (that's affordability_score()'s job)."""
    text = text or ""
    if _CITIZENSHIP_RE.search(text):
        return (0, "citizenship/residency bar")

    if is_online is True:
        return (_ATTENDANCE_MAX, "online")

    if _is_local_kazakhstan(location):
        return (_ATTENDANCE_LOCAL, "in Kazakhstan, no flight needed")

    if is_online is None:
        return (_ATTENDANCE_UNKNOWN, "format unknown")

    return (0, "in-person, requires international travel")


# --- selectivity (0-5) ------------------------------------------------------

# Explicit acceptance-rate/cap language. Matches with a digit in them
# ("15% acceptance", "only 20 spots", "5 accepted out of 200") are the
# strong signal; matches without a digit ("highly selective", "competitive
# admission") are weaker -- classified post-match rather than as two
# separate regexes, so there's still exactly one selectivity regex group.
_SELECTIVITY_PATTERNS = [
    r"\d+(?:\.\d+)?\s?%\s*(?:acceptance|admission|admit|selection)(?:\s*rate)?",
    r"only\s+\d+\s*(?:spots?|seats?|slots?|positions?|places?)",
    r"\d+\s*(?:accepted|selected|admitted)\s*(?:out of|of)\s*\d+",
    r"highly selective",
    r"competitive admission",
]
_SELECTIVITY_RE = re.compile("|".join(_SELECTIVITY_PATTERNS), re.IGNORECASE)

_SELECTIVITY_NUMERIC_MAX = 5
_SELECTIVITY_INSTITUTION_FLOOR = 3
_SELECTIVITY_VAGUE = 2


def selectivity_score(text: str | None) -> tuple[int, str]:
    """(score 0-5, reason). An explicit numeric acceptance-rate/cap claim
    maxes the axis; a flagship institution's name alone (see
    _FLAGSHIP_INSTITUTIONS) earns a smaller floor even with no number;
    vague selectivity language with no number and no flagship name is the
    weakest signal."""
    text = text or ""
    matches = list(_SELECTIVITY_RE.finditer(text))
    numeric = [m for m in matches if re.search(r"\d", m.group(0))]
    vague = [m for m in matches if not re.search(r"\d", m.group(0))]

    if numeric:
        return (_SELECTIVITY_NUMERIC_MAX, numeric[0].group(0).strip())

    if _FLAGSHIP_INSTITUTIONS_RE.search(text):
        return (_SELECTIVITY_INSTITUTION_FLOOR, "known-institution floor")

    if vague:
        return (_SELECTIVITY_VAGUE, vague[0].group(0).strip())

    return (0, "no selectivity signal")


# --- prestige / brand (0-20) ------------------------------------------------

# Flagship institutions/orgs/programs -- a plain list constant, not inlined
# into the regex, since this will need tuning over time as new names come up.
# Short acronyms are word-boundary matched via _FLAGSHIP_INSTITUTIONS_RE
# below, so "YC" doesn't match inside an unrelated word.
_FLAGSHIP_INSTITUTIONS = [
    "MIT", "Massachusetts Institute of Technology",
    "Stanford", "Harvard", "Caltech", "Princeton", "Yale",
    "Berkeley", "UC Berkeley", "Carnegie Mellon", "CMU",
    "Oxford", "Cambridge", "ETH Zurich",
    "Google", "DeepMind", "OpenAI", "Meta AI", "Microsoft Research",
    "Y Combinator", "YC", "Techstars",
    "ICPC", "IOI", "IMO",
]
_FLAGSHIP_INSTITUTIONS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in _FLAGSHIP_INSTITUTIONS) + r")\b",
    re.IGNORECASE,
)

# A recognized-but-non-flagship org name is hard to enumerate exhaustively,
# so instead of a second institutions list this looks for the generic
# "there is clearly some organization involved" markers -- weaker than a
# flagship name, but still more than nothing.
_ORG_MARKER_RE = re.compile(
    r"\buniversity\b|\binstitute\b|\bfoundation\b|\bcorporation\b|\bcompany\b|\bcollege\b",
    re.IGNORECASE,
)

_PRESTIGE_FLAGSHIP_BASE = 16
_PRESTIGE_FLAGSHIP_MAX = 20
_PRESTIGE_FLAGSHIP_BONUS_MAX = 4
_PRESTIGE_NOTABLE = 8


def prestige_score(text: str | None) -> tuple[int, str]:
    """(score 0-20, reason). Brand recognition only -- does not re-score the
    acceptance-rate/cap numbers selectivity_score() already covers.

      Flagship (16-20): one or more flagship institution/org matches (see
        _FLAGSHIP_INSTITUTIONS). +2 per additional distinct match, capped at 20.
      Notable (8): no flagship name, but a generic organization marker
        (university/institute/foundation/corporation/company/college) is
        present.
      Generic (0): neither -- no recognizable brand at all.
    """
    text = text or ""
    inst_matches = list(_FLAGSHIP_INSTITUTIONS_RE.finditer(text))
    if inst_matches:
        distinct = sorted({m.group(0).strip().lower() for m in inst_matches})
        bonus = min(_PRESTIGE_FLAGSHIP_BONUS_MAX, 2 * (len(distinct) - 1))
        value = min(_PRESTIGE_FLAGSHIP_MAX, _PRESTIGE_FLAGSHIP_BASE + bonus)
        return (value, " + ".join(distinct[:2]))

    org_match = _ORG_MARKER_RE.search(text)
    if org_match:
        return (_PRESTIGE_NOTABLE, org_match.group(0).strip())

    return (0, "no institution/brand signal")


# --- topic fit (0-15) --------------------------------------------------

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

# Bases on a 0-15 budget (rescaled proportionally from the old 0-40 fit axis:
# 34/40, 22/40, 10/40, 0/40 of the budget).
_TIER_BASE = {4: 13, 3: 8, 2: 4, 1: 0}
_FIT_BONUS_MAX = 2
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


def topic_fit_score(text: str) -> tuple[int, str]:
    """(score 0-15, reason). Fixed tier base + up to +2 for multiple distinct
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


# --- output value (0-10) ----------------------------------------------------

# Concrete prize/output language -- cash prizes, scholarship dollar amounts,
# publication opportunities, demo days. Deliberately distinct phrasing from
# _FUNDING_RE ("scholarship" alone is an affordability signal; "scholarship
# award" plus a dollar figure is an output-value signal) so the two axes
# don't double-count the same word.
#
# The dollar-amount patterns require a prize/award/scholarship/grant word
# next to the figure -- a bare "$" next to any number reads program tuition
# ("Camp costs $1,875") as a prize just as readily as an actual one ("$1,875
# scholarship"), which real backlog data confirmed: dozens of plain paid
# summer camps were scoring a "prize" purely off their price tag.
_PRIZE_PATTERNS = [
    r"\$\s?\d[\d,]*\s*(?:in\s+)?(?:cash\s+)?(?:prizes?|awards?|scholarships?|grants?)\b",
    r"(?:cash\s+prizes?|scholarship\s+awards?|prizes?|awards?|grants?)\s+"
    r"(?:of|worth|totaling|totalling)\s+\$\s?\d[\d,]*",
    r"cash prize",
    r"scholarship award",
    r"\bpublish(?:ed|ing)?\b",
    r"demo day",
]
_PRIZE_RE = re.compile("|".join(_PRIZE_PATTERNS), re.IGNORECASE)

_OUTPUT_MAX = 10
_OUTPUT_BASE = 6
_OUTPUT_BONUS_MAX = 4


def output_value_score(text: str | None) -> tuple[int, str]:
    """(score 0-10, reason). Concrete prize/scholarship-dollar-amount or
    publication/demo-day language -- see _PRIZE_PATTERNS."""
    text = text or ""
    matches = list(_PRIZE_RE.finditer(text))
    if not matches:
        return (0, "no prize/output signal")

    distinct = sorted({m.group(0).strip().lower() for m in matches})
    bonus = min(_OUTPUT_BONUS_MAX, 2 * (len(distinct) - 1))
    value = min(_OUTPUT_MAX, _OUTPUT_BASE + bonus)
    return (value, distinct[0])


# --- combined score ------------------------------------------------------

# Opportunity.relevance_reason is a String(120) column. Assignment on an
# already-constructed OpportunityDTO (src/processor/pipeline.py's Telegram
# path) bypasses pydantic validators entirely, so length has to be enforced
# here to be safe for both callers.
_MAX_REASON_LEN = 120

# Axes in display order, paired with the order (by index into this same
# tuple) their parenthetical rationale gets dropped first if the full reason
# would overflow _MAX_REASON_LEN -- lowest max-points axes lose their label
# first, so affordability/attendance-ability (the two highest-weight axes)
# keep theirs the longest.
_AXIS_DISPLAY_ORDER = ("aff", "att", "sel", "pres", "fit", "out")
_AXIS_DROP_PRIORITY = ("sel", "out", "fit", "pres", "att", "aff")


def _build_reason(values: dict[str, tuple[int, int, str]]) -> str:
    """values: axis code -> (score, max, label). Joins in display order,
    shortest full form first; if that overflows _MAX_REASON_LEN, drops
    parenthetical labels one axis at a time in `_AXIS_DROP_PRIORITY` order
    before finally hard-truncating as a last resort."""

    def build(hidden: set[str]) -> str:
        parts = []
        for code in _AXIS_DISPLAY_ORDER:
            score, mx, label = values[code]
            if code in hidden:
                parts.append(f"{code} {score}/{mx}")
            else:
                parts.append(f"{code} {score}/{mx} ({label})")
        return " + ".join(parts)

    hidden: set[str] = set()
    reason = build(hidden)
    if len(reason) <= _MAX_REASON_LEN:
        return reason

    for code in _AXIS_DROP_PRIORITY:
        hidden.add(code)
        reason = build(hidden)
        if len(reason) <= _MAX_REASON_LEN:
            return reason

    return reason[: _MAX_REASON_LEN - 3] + "..."


def score(
    is_online: bool | None,
    cost_amount: float | None,
    location: str | None,
    text: str,
    small_fee_usd: float = 50.0,
) -> tuple[int, str]:
    """(score 0-100, reason). `text` should include title, description and
    eligibility at minimum -- everywhere funding, citizenship and topic-fit
    keywords might appear."""
    text = text or ""
    aff, aff_label = affordability_score(cost_amount, text, small_fee_usd)
    att, att_label = attendance_ability_score(is_online, location, text)
    sel, sel_label = selectivity_score(text)
    pres, pres_label = prestige_score(text)
    fit, fit_label = topic_fit_score(text)
    out, out_label = output_value_score(text)

    value = aff + att + sel + pres + fit + out
    reason = _build_reason(
        {
            "aff": (aff, _AFFORDABILITY_MAX, aff_label),
            "att": (att, _ATTENDANCE_MAX, att_label),
            "sel": (sel, _SELECTIVITY_NUMERIC_MAX, sel_label),
            "pres": (pres, _PRESTIGE_FLAGSHIP_MAX, pres_label),
            "fit": (fit, 15, fit_label),
            "out": (out, _OUTPUT_MAX, out_label),
        }
    )
    return (value, reason)
