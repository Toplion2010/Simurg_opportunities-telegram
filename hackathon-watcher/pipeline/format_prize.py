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
            return prize_text or None

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
            return prize_text or f"{len(prize_breakdown)} prizes"

        if cash:
            total = _format_amount(sum(amount for _, amount in cash))
            symbol = next(iter(currencies))
            pool = f"Prize pool {symbol}{total}"
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

        return prize_text or None
    except Exception:
        logger.warning("format_prize: failed to summarize %r", prize_breakdown, exc_info=True)
        return prize_text or None
