"""Can a Kazakh student actually reach this opportunity?

The admission rule, as specified:

  1. it is online                                        -> admit
  2. it is offline, but there is a plausible route to a
     grant/funding for a Kazakh student to attend        -> admit
  3. it is free, or costs only a small fee               -> admit

Implemented as **reject only when provably closed**, which is the same posture
as the hackathon watcher's `online_only` filter (`is_online is not False`):
unknown always passes. These catalogs are US-centric and often silent about
eligibility, and dropping an item on silence would throw away most of the real
yield. The admin queue is the second gate; a false admit costs one review, a
false reject is invisible and permanent.

NOT to be confused with src/core/geo.match_kazakhstan. That answers "is this
opportunity IN Kazakhstan" for hackathon-channel routing. This answers "can a
Kazakh student GET to this". Keep them separate.
"""
import re

REASON_ADMITTED = "admitted"
REASON_CITIZENSHIP = "citizenship_or_residency_bar"
REASON_UNFUNDED_IN_PERSON = "in_person_priced_no_funding"
REASON_FUNDED_OFFICIAL = "funding_found_on_official_site"
REASON_CLOSED = "applications_closed"

# These catalogs keep listings up after the fact and say so in the deadline
# field. Observed live: "Applications closed". Reaching the admin queue as
# "apply by Applications closed" wastes a review on something nobody can apply
# to. Only an EXPLICIT closed statement counts — a missing deadline is unknown,
# and "Rolling applications" is open.
_CLOSED_RE = re.compile(
    r"^\s*(?:applications?\s+)?(?:are\s+)?clos(?:ed|ing)\b|"
    r"^\s*(?:no longer|not)\s+accepting|"
    r"^\s*(?:deadline\s+)?(?:has\s+)?passed\b",
    re.IGNORECASE,
)

# A hard legal bar, not a preference. The NSF-REU family ("US citizens,
# nationals, or permanent residents") is the single highest-volume exclusion in
# these catalogs, and no amount of funding lifts it.
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

# Any of these makes an expensive in-person program admissible under limb 2:
# the money is not necessarily a wall.
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


def find_funding(text: str | None) -> list[str]:
    """Distinct funding signals present in `text`, lowercased and deduped.

    Split out from admits() because the catalogs themselves are nearly
    prose-free: across 45 real ExtracurricularHub listings, ZERO contained any
    funding language, so this limb of the rule could never fire on catalog data
    alone. It has to be run against the OFFICIAL page — where, in a 6-of-6
    sample of items the filter had rejected, every single one turned out to
    offer a scholarship, need-based aid, or both.

    Kept pure: the caller does the fetching (see collector/web/fetcher.py).
    """
    if not text:
        return []
    return sorted({m.group(0).lower() for m in _FUNDING_RE.finditer(text)})


def _haystack(item) -> str:
    return " ".join(
        filter(
            None,
            [
                item.title,
                item.description,
                item.eligibility,
                item.cost_text,
                item.organizer,
            ],
        )
    )


def admits(item, small_fee_usd: float = 50.0) -> tuple[bool, str]:
    """Return (admitted, reason). The reason is returned in BOTH cases so a
    misfiring pattern shows up in the run log without a redeploy."""
    text = _haystack(item)

    if item.deadline and _CLOSED_RE.search(item.deadline):
        return (False, REASON_CLOSED)

    if _CITIZENSHIP_RE.search(text):
        return (False, REASON_CITIZENSHIP)

    # Limb 1: online is admitted regardless of price. An online course a
    # student could apply to a sponsor for is still reachable; a plane ticket
    # is the thing that is not.
    if item.is_online is not False:
        return (True, REASON_ADMITTED)

    # Limb 3: free or a small fee. Unknown price is unknown, not expensive.
    if item.cost_amount is None or item.cost_amount <= small_fee_usd:
        return (True, REASON_ADMITTED)

    # Limb 2: in person and genuinely expensive — admit only on a funding signal.
    if _FUNDING_RE.search(text):
        return (True, REASON_ADMITTED)

    return (False, REASON_UNFUNDED_IN_PERSON)
