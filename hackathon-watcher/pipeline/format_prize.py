"""Collapses an itemized prize breakdown into one short, scannable phrase
for the Telegram post's headline line. Never invents or estimates a
number — anything ambiguous degrades to a vaguer-but-true summary.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_MONEY_RE = re.compile(
    r"(?:(?P<sym>[$€£₹])|(?P<code1>USD|EUR|GBP|INR|CAD|AUD)\b)\s*(?P<amt1>[\d,]+(?:\.\d+)?)"
    r"|(?P<amt2>[\d,]+(?:\.\d+)?)\s*(?P<code2>USD|EUR|GBP|INR|CAD|AUD)\b"
)

# Static, approximate rates — not a live FX feed (no new paid dependency).
# Good enough for a rough "(~$X)" hint on a prize figure, not for anything
# that needs precision. USD itself maps to 1.0 so no suffix gets added.
_USD_RATES: dict[str, float] = {
    "$": 1.0, "USD": 1.0,
    "€": 1.08, "EUR": 1.08,
    "£": 1.27, "GBP": 1.27,
    "₹": 0.012, "INR": 0.012,
    "CAD": 0.73,
    "AUD": 0.66,
}


def _usd_estimate(currency: str, amount: float) -> str | None:
    rate = _USD_RATES.get(currency.upper())
    if rate is None or rate == 1.0 or amount <= 0:
        return None
    usd = amount * rate
    usd_str = f"{usd:,.0f}" if usd >= 100 else f"{usd:,.2f}"
    return f"~${usd_str}"


def _with_usd_suffix(text: str) -> str:
    """Appends a '(~$X)' hint only when `text` IS a bare money value (e.g.
    '₹40,00,000') — never for free-form text with a number embedded in a
    sentence, where guessing which figure to convert would be misleading."""
    try:
        stripped = text.strip()
        match = _MONEY_RE.search(stripped)
        if not match:
            return text
        remainder = (stripped[: match.start()] + stripped[match.end() :]).strip()
        if remainder:
            return text
        money = _parse_money(stripped)
        if not money:
            return text
        currency, amount = money
        usd = _usd_estimate(currency, amount)
        return f"{text} ({usd})" if usd else text
    except Exception:
        return text


def _parse_money(text: str) -> tuple[str, float] | None:
    match = _MONEY_RE.search(text)
    if not match:
        return None
    currency = match.group("sym") or match.group("code1") or match.group("code2")
    amount_str = match.group("amt1") or match.group("amt2")
    try:
        return currency, float(amount_str.replace(",", ""))
    except ValueError:
        return None


def _format_amount(amount: float) -> str:
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


def summarize_prize(prize_breakdown: list[str], prize_text: str | None) -> str | None:
    """`prize_breakdown` items look like 'Title: Value' (e.g. '1st Prize:
    $500 of USDT') or bare non-cash values. Returns None only when nothing
    usable exists at all — callers omit the whole prize line in that case."""
    try:
        if not prize_breakdown:
            return _with_usd_suffix(prize_text) if prize_text else None

        cash: list[tuple[str, float]] = []
        noncash: list[tuple[str, str]] = []  # (label, value-as-shown)

        for item in prize_breakdown:
            if ":" in item:
                label, value = item.split(":", 1)
                label, value = label.strip(), value.strip()
            else:
                label, value = item.strip(), item.strip()
            if not value:
                continue
            money = _parse_money(value)
            if money:
                cash.append(money)
            else:
                noncash.append((label, value))

        currencies = {c for c, _ in cash}

        if len(currencies) > 1:
            # Different currencies can't be summed without a conversion
            # rate, and a stale rate is worse than a vague summary.
            return (_with_usd_suffix(prize_text) if prize_text else None) or f"{len(prize_breakdown)} prizes"

        if cash:
            total_amount = sum(amount for _, amount in cash)
            total = _format_amount(total_amount)
            symbol = next(iter(currencies))
            pool = f"Prize pool {symbol}{total}"
            usd = _usd_estimate(symbol, total_amount)
            if usd:
                pool = f"{pool} ({usd})"
            if noncash:
                # Non-cash items carry no comparable number, so "highest
                # value" falls back to breakdown order — items are already
                # ranked 1st/2nd/3rd/etc. by the source.
                _, top_value = noncash[0]
                return f"{pool} + {top_value}"
            return pool

        if noncash:
            _, top_value = noncash[0]
            return top_value

        return _with_usd_suffix(prize_text) if prize_text else None
    except Exception:
        logger.warning("format_prize: failed to summarize %r", prize_breakdown, exc_info=True)
        return prize_text or None
