"""Turn a WebItem into an OpportunityDTO WITHOUT calling the LLM.

This is the cost decision that makes web ingestion viable at all. Groq's free
tier is ~100k tokens/day and the Telegram pipeline already runs near it
(MAX_MESSAGES_PER_RUN=7 exists for that reason). Sending ~1,900 catalog items
through extractor.py would spend the day's budget re-deriving fields the
catalogs already state as structured data — and starve the Telegram pipeline,
which is the core product.

So: map the fields straight across, and compose the prose fields from those
facts with fixed templates. What we cannot do deterministically we leave None:

  category   — left None on purpose. CategoryClassifier already does a free
               keyword pass (src/processor/classifier.py), and a wrong guess
               here would route an item to the wrong channel.
  relevance  — left None. It is the LLM's profile-fit judgement; faking a
               number would corrupt the queue's ranking. Unrated items sort
               last, which is the correct place for unreviewed scraped input.

Card copy from this path is plainer than the LLM's. That is an accepted
trade, and the admin queue's Edit flow (src/bot/routers/edit.py) is the
escape hatch for any individual item worth polishing.
"""
import re

from src.collector.web.base import WebItem
from src.processor.age import parse_min_age
from src.processor.extractor import OpportunityDTO

_SCHOOL_HINTS = re.compile(
    r"\b(?:k-?12|middle school|high school|elementary|grade[s]?\s*\d|"
    # SIREL's grade taxonomy labels are bare ordinals — "9th", "12th" — with no
    # following "grade". Bounded at 12 so a "20th anniversary" in free-text
    # eligibility cannot read as a school year.
    r"(?:[1-9]|1[0-2])(?:st|nd|rd|th)|"
    r"pupils?|schoolchildren)\b",
    re.IGNORECASE,
)
# Plurals are explicit: a trailing \b after a bare stem does NOT match
# "Undergraduates", and catalogs write these in the plural far more often than
# the singular.
_UNIVERSITY_HINTS = re.compile(
    r"\b(?:undergraduates?|universit(?:y|ies)|colleges?|graduates?|master'?s|"
    r"phds?|doctoral|postgraduates?|bachelors?)\b",
    re.IGNORECASE,
)


def _fit(text: str | None, limit: int) -> str | None:
    """Trim to `limit` on a word boundary, never mid-word.

    The card renderer's caps are hard, but a truncated word reads as a bug. If
    a single clause cannot fit, better to return the clause we can fit whole.
    """
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-—")
    return cut or None


def _cost_text(item: WebItem) -> str | None:
    if item.cost_text:
        return item.cost_text
    if item.cost_amount is None:
        return None
    if item.cost_amount == 0:
        return "Free"
    currency = item.cost_currency or "USD"
    amount = int(item.cost_amount) if item.cost_amount.is_integer() else item.cost_amount
    return f"{amount} {currency}"


def _location(item: WebItem) -> str | None:
    if item.is_online is True and not item.country:
        return "Online"
    if item.country and item.is_online is True:
        return f"{item.country} / Online"
    return item.country


def _audience(item: WebItem) -> str | None:
    """school / university / None(-> both).

    Deliberately conservative, matching the extractor prompt's own rule: an
    unqualified "students" is never enough to narrow to university, and when
    both sets of hints appear the answer is both (None).
    """
    text = " ".join(item.grades + [item.eligibility or ""])
    has_school = bool(_SCHOOL_HINTS.search(text))
    has_university = bool(_UNIVERSITY_HINTS.search(text))
    if has_school and not has_university:
        return "school"
    if has_university and not has_school:
        return "university"
    return None


def _description(item: WebItem) -> str:
    """The item's own description when it has a real one, else a factual
    sentence built from the fields. Never marketing, never inferred."""
    if item.description:
        return item.description
    bits = [item.title]
    if item.organizer:
        bits.append(f"organised by {item.organizer}")
    where = _location(item)
    if where:
        bits.append(f"({where})")
    sentence = " ".join(bits).strip()
    extras = []
    if item.eligibility:
        extras.append(f"Eligibility: {item.eligibility}.")
    cost = _cost_text(item)
    if cost:
        extras.append(f"Cost: {cost}.")
    if item.deadline:
        extras.append(f"Deadline: {item.deadline}.")
    elif item.starts_at:
        extras.append(f"Starts: {item.starts_at}.")
    return " ".join([f"{sentence}." if sentence else "", *extras]).strip()


def build_dto(item: WebItem) -> OpportunityDTO:
    cost = _cost_text(item)
    description = _description(item)
    where = _location(item)

    # Age floor from whatever the catalog stated, using the SAME parser the
    # Telegram path uses — a second age parser would drift from the age gate.
    min_age = parse_min_age(" ".join(filter(None, [item.eligibility, item.title])))

    # card_summary must be one self-contained sentence under 130 chars. Build a
    # short one rather than truncating the long description into nonsense.
    summary_bits = [item.title]
    if where:
        summary_bits.append(f"— {where}")
    if item.deadline:
        summary_bits.append(f", apply by {item.deadline}")
    card_summary = _fit(" ".join(summary_bits).replace(" ,", ","), 130) or _fit(
        item.title, 130
    )

    rewards = None
    if cost and cost.lower() == "free":
        rewards = "Free to enter"

    additional_links = []
    if item.apply_url and item.page_url and item.apply_url != item.page_url:
        # Keep the catalog page too — it often carries context the official
        # site buries, and source_url already points there for provenance.
        additional_links.append(item.page_url)

    return OpportunityDTO(
        is_opportunity=True,
        title=item.title,
        category=None,  # see module docstring — CategoryClassifier decides
        audience=_audience(item),
        deadline=item.deadline,
        eligibility=item.eligibility,
        location=where,
        cost=cost,
        organizer=item.organizer,
        duration=item.duration,
        rewards=rewards,
        apply_link=item.apply_url or item.page_url,
        description=description,
        rewritten_text=description,
        card_summary=card_summary,
        card_eligibility=_fit(item.eligibility, 90),
        card_rewards=_fit(rewards or cost, 90),
        additional_links=additional_links,
        extra_notes=None,
        source_excerpt=_fit(description, 400),
        min_age=min_age,
        relevance=None,  # see module docstring
        relevance_reason=None,
    )
