"""Rough USD value of an opportunity's prize pool, from its free-text fields.

Decides whether a published hackathon is big enough for an automatic Story
(src/publisher/scheduler.py). Only amounts written next to a currency marker
count, so years, dates and team sizes never read as money. Conversion rates
are deliberately rough and fixed: this answers "is it around $5k or more",
not accounting questions.
"""
import re

from src.db.models.opportunity import Opportunity

_USD_PER = {"usd": 1.0, "eur": 1.08, "gbp": 1.27, "kzt": 1 / 480, "rub": 1 / 90}

_CURRENCY = {
    "usd": r"\$|us\$|usd|dollars?|долл\w*",
    "eur": r"€|eur|euros?|евро",
    "gbp": r"£|gbp|pounds?",
    "kzt": r"₸|kzt|тенге|tenge|тг",
    "rub": r"₽|rub|руб\w*|rubles?|roubles?",
}
_CUR = "|".join(f"(?P<{code}@N>{pattern})" for code, pattern in _CURRENCY.items())
# "1 000 000", "1,000,000", "1.000.000", "1,5", "10", "2.5"
_NUM = r"(?P<num@N>\d{1,3}(?:[ ,.  ]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)"
_MULT = r"(?:\s?(?P<mult@N>k|к|тыс\.?|thousand|m|mln|million|млн|миллион\w*)(?!\w))?"


def _compile(template: str, n: int) -> re.Pattern:
    return re.compile(template.replace("@N", str(n)), re.IGNORECASE)


_PREFIXED = _compile(rf"(?:{_CUR})\s?{_NUM}{_MULT}", 1)
_SUFFIXED = _compile(rf"{_NUM}{_MULT}\s?(?:{_CUR})", 2)

_THOUSANDS = re.compile(r"\d{1,3}(?:[ ,.  ]\d{3})+")


def _number(raw: str) -> float:
    if _THOUSANDS.fullmatch(raw):
        return float(re.sub(r"\D", "", raw))
    return float(raw.replace(",", "."))


def _multiplier(raw: str | None) -> float:
    if not raw:
        return 1.0
    raw = raw.lower()
    if raw[0] in "kк" or raw.startswith(("тыс", "thousand")):
        return 1e3
    return 1e6


def prize_usd(text: str | None) -> float | None:
    """Largest currency amount in `text`, converted to USD, or None if none."""
    if not text:
        return None
    best = None
    for regex, n in ((_PREFIXED, 1), (_SUFFIXED, 2)):
        for m in regex.finditer(text):
            groups = m.groupdict()
            code = next(c for c in _CURRENCY if groups.get(f"{c}{n}"))
            value = _number(groups[f"num{n}"]) * _multiplier(groups[f"mult{n}"]) * _USD_PER[code]
            best = value if best is None else max(best, value)
    return best


def opportunity_prize_usd(opp: Opportunity) -> float | None:
    # The description is only a fallback: it often mentions unrelated money
    # (tuition, a sponsor's funding round) that would fake a big prize.
    amounts = [prize_usd(opp.rewards), prize_usd(opp.card_rewards)]
    found = [a for a in amounts if a is not None]
    if found:
        return max(found)
    if opp.rewards or opp.card_rewards:
        return None
    return prize_usd(opp.description)
