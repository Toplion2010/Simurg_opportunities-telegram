"""A 0-100 relevance score combining reachability ("coolness"), profile fit,
and prestige.

Used by both collector pipelines (Telegram via src/processor/pipeline.py, web
catalogs via src/collector/web/to_dto.py) so an opportunity's rank in the
admin queue -- and now the daily digest's auto-approve/review split -- means
the same thing regardless of where it came from. Lives in core/ rather than
processor/ or collector/web/ for the same reason geo.py does: both siblings
need it, and neither should import from the other.

Replaces an earlier 1-10 table (reachability tier x fit tier, 16 cells) that
was too coarse once the job became "pick the real top 5 out of hundreds of
pending rows a day" rather than just "sort a queue a human browses by hand".
All three axes are continuous point totals instead of table lookups, so ties
are rare.

  COOLNESS (0-40) -- can a Kazakh student actually get there, and how good
  is the deal. Built on the same reachability tiers as before (R1..R4, see
  reachability_tier()), plus a continuous bonus for how strong the signal is
  within that tier. Internally this is the same 0-60 tier-floor-plus-bonus
  computation the table above used to be scored on, scaled down by /1.5 (and
  rounded) so it now shares the 0-100 budget with a third axis:

    R1 (0)         in-person, priced, unfunded, not Kazakhstan-local -- or
                   the citizenship/residency bar. No bonus; this is the
                   score floor.
    R2 (10-17)     free/cheap in-person with no funding language, or
                   genuinely unknown online-ness AND cost. Bonus scales with
                   how far under WEB_SMALL_FEE_USD the (known) cost is; an
                   unknown cost gets a flat mid-range bonus.
    R3 (25-30)     partial funding, not Kazakhstan-local. Bonus scales with
                   how many distinct funding signals were found
                   (find_funding()) -- "scholarship" alone reads weaker than
                   "scholarship, financial aid, stipend" together.
    R4 (38 or 40)  online, OR fully funded, OR Kazakhstan-local and
                   funded/cheap. Binary bonus: the max (40) for online or
                   full funding, slightly less (38) for the KZ-local case,
                   since a local program still costs the price of a bus
                   ticket at worst.

  The tier ranges never overlap, so coolness alone already orders every
  reachability outcome correctly.

  Citizenship/residency-bar clamp: this zeroes out ONLY coolness (R1, see
  above) -- it does not zero fit or prestige, and never zeroes the total.
  A citizenship-barred MIT program still surfaces in the admin queue,
  low-ranked on coolness alone but with fit and prestige intact, rather than
  vanishing silently. The reason string keeps the "citizenship/residency
  bar" tag so the eligibility problem is obvious without re-reading the
  listing.

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

  PRESTIGE (0-20) -- selectivity, brand recognition, and concrete
  prize/output language. Deliberately disjoint from coolness (does not
  re-score funding amounts as reachability) and from fit (does not re-score
  topic words as profile match) -- it only fires on separate signals:
  flagship institutions/orgs, explicit acceptance-rate or cap language, and
  prize/scholarship-amount or publication/demo-day language. See
  prestige_score() for the tier breakdown.

`score()` returns COOLNESS + FIT + PRESTIGE (0-100) and a reason naming all
three components' rationale, auditable straight off a queue card or a daily
digest push, e.g.:

    "cool 40/40 (online) + fit 34/40 (core: computer vision) + prestige 18/20 (MIT + selective (15% acceptance))"
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


# --- coolness (0-40) --------------------------------------------------------

# These floors/bonus are on the original 0-60 scale; coolness_score() scales
# the final floor+bonus total down by _COOLNESS_SCALE before returning it, so
# the tier structure and bonus logic below are untouched from the 1-10
# table's replacement -- only the shared 0-100 budget changed.
_REACH_FLOOR = {R1: 0, R2: 15, R3: 30, R4: 45}
_REACH_BONUS_MAX = 15
_COOLNESS_SCALE = 1.5


def coolness_score(
    is_online: bool | None,
    cost_amount: float | None,
    location: str | None,
    text: str,
    small_fee_usd: float = 50.0,
) -> tuple[int, str]:
    """(score 0-40, reason). Continuous version of reachability_tier(): the
    tier sets a floor, a same-tier bonus separates a strong signal (fully
    funded, $0 fee) from a weak one (one funding phrase, $45 of a $50 cap).
    """
    text = text or ""
    tier, label = reachability_tier(is_online, cost_amount, location, text, small_fee_usd)
    floor = _REACH_FLOOR[tier]

    if tier == R1:
        return (0, label)

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

    return (round((floor + bonus) / _COOLNESS_SCALE), label)


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


# --- prestige (0-20) --------------------------------------------------------

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

# Explicit acceptance-rate/cap language. Matches with a digit in them
# ("15% acceptance", "only 20 spots", "5 accepted out of 200") are the
# strong, Flagship-tier signal; matches without a digit ("highly selective",
# "competitive admission") are the weaker, Notable-tier signal -- classified
# post-match in prestige_score() rather than as two separate regexes, so
# there's still exactly one selectivity regex group as specified.
_SELECTIVITY_PATTERNS = [
    r"\d+(?:\.\d+)?\s?%\s*(?:acceptance|admission|admit|selection)(?:\s*rate)?",
    r"only\s+\d+\s*(?:spots?|seats?|slots?|positions?|places?)",
    r"\d+\s*(?:accepted|selected|admitted)\s*(?:out of|of)\s*\d+",
    r"highly selective",
    r"competitive admission",
]
_SELECTIVITY_RE = re.compile("|".join(_SELECTIVITY_PATTERNS), re.IGNORECASE)

# Concrete prize/output language -- cash prizes, scholarship dollar amounts,
# publication opportunities, demo days. Deliberately distinct phrasing from
# _FUNDING_RE ("scholarship" alone is a coolness/reachability signal;
# "scholarship award" plus a dollar figure is a prestige signal) so the two
# axes don't double-count the same word.
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

# A recognized-but-non-flagship org name is hard to enumerate exhaustively,
# so instead of a second institutions list this looks for the generic
# "there is clearly some organization involved" markers -- weaker than a
# flagship name, but still more than nothing.
_ORG_MARKER_RE = re.compile(
    r"\buniversity\b|\binstitute\b|\bfoundation\b|\bcorporation\b|\bcompany\b|\bcollege\b",
    re.IGNORECASE,
)

_PRESTIGE_FLAGSHIP_BASE = 14
_PRESTIGE_FLAGSHIP_MAX = 20
_PRESTIGE_NOTABLE_MAX = 13


def prestige_score(text: str | None) -> tuple[int, str]:
    """(score 0-20, reason). Selectivity, brand recognition, and prize/output
    language -- disjoint from coolness (funding amounts) and fit (topic
    words); see the module docstring's PRESTIGE section for the three
    underlying signal groups.

      Flagship (14-20): a flagship institution/org match, and/or an explicit
        acceptance-rate or cap number. +2 per additional distinct signal
        across all three regex groups, capped at 20.
      Notable (7-13): prize/scholarship-amount language with no institution
        match, OR vague selectivity language with no explicit rate/cap
        number, OR a non-flagship org name present. +1 per additional
        distinct category present, capped at 13.
      Generic (0): none of the above -- open enrollment, no cap, unknown
        organizer, recurring/low-stakes format.
    """
    text = text or ""
    inst_match = _FLAGSHIP_INSTITUTIONS_RE.search(text)
    selectivity_matches = list(_SELECTIVITY_RE.finditer(text))
    prize_matches = list(_PRIZE_RE.finditer(text))
    numeric_selectivity = [m for m in selectivity_matches if re.search(r"\d", m.group(0))]
    vague_selectivity = [m for m in selectivity_matches if not re.search(r"\d", m.group(0))]
    org_marker_match = None if inst_match else _ORG_MARKER_RE.search(text)

    if inst_match or numeric_selectivity:
        parts = []
        if inst_match:
            parts.append(inst_match.group(0).strip())
        parts += [m.group(0).strip() for m in selectivity_matches]
        parts += [m.group(0).strip() for m in prize_matches]
        distinct = sorted({p.lower(): p for p in parts}.values())
        bonus = min(6, 2 * max(0, len(distinct) - 1))
        value = min(_PRESTIGE_FLAGSHIP_MAX, _PRESTIGE_FLAGSHIP_BASE + bonus)
        reason = " + ".join(distinct[:3])
        return (value, reason)

    if prize_matches or vague_selectivity or org_marker_match:
        candidates = []
        parts = []
        if prize_matches:
            candidates.append(13)
            parts += [m.group(0).strip() for m in prize_matches]
        if vague_selectivity:
            candidates.append(10)
            parts += [m.group(0).strip() for m in vague_selectivity]
        if org_marker_match:
            candidates.append(7)
            parts.append(org_marker_match.group(0).strip())
        base = max(candidates)
        value = min(_PRESTIGE_NOTABLE_MAX, base + (len(candidates) - 1))
        distinct = sorted({p.lower(): p for p in parts}.values())
        reason = " + ".join(distinct[:3])
        return (value, reason)

    return (0, "no institution/selectivity/prize signals")


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
    prestige, prestige_label = prestige_score(text)
    value = cool + fit + prestige
    reason = (
        f"cool {cool}/40 ({cool_label}) + fit {fit}/40 ({fit_label}) "
        f"+ prestige {prestige}/20 ({prestige_label})"
    )
    if len(reason) > _MAX_REASON_LEN:
        reason = reason[: _MAX_REASON_LEN - 3] + "..."
    return (value, reason)
