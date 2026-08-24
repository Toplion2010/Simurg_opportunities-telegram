from __future__ import annotations

from pipeline.format_prize import summarize_prize


def test_all_cash_same_currency_sums():
    result = summarize_prize(
        ["1st Prize: $500 of USDT", "2nd Prize: $200 of USDT"], None
    )
    assert result == "Prize pool $700"


def test_cash_various_formats_sum():
    result = summarize_prize(
        ["Gold: $405 in cash", "Silver: $200 in cash", "Bronze: $110 in cash"], None
    )
    assert result == "Prize pool $715"


def test_mixed_cash_and_noncash_appends_top_item():
    result = summarize_prize(
        ["1st Prize: $500 in cash", "Bonus: iPhone 15"], None
    )
    assert result == "Prize pool $500 + iPhone 15"


def test_noncash_only_names_top_item_verbatim():
    result = summarize_prize(["Grand Prize: iPhone 15 Pro"], None)
    assert result == "iPhone 15 Pro"


def test_noncash_only_bare_item_no_colon():
    result = summarize_prize(["Sponsored trip to SF"], None)
    assert result == "Sponsored trip to SF"


def test_mixed_currencies_falls_back_to_prize_text():
    result = summarize_prize(["1st: $500", "2nd: €200"], "$5,000 total")
    assert result == "$5,000 total"


def test_mixed_currencies_no_prize_text_falls_back_to_count():
    result = summarize_prize(["1st: $500", "2nd: €200"], None)
    assert result == "2 prizes"


def test_empty_breakdown_falls_back_to_prize_text():
    assert summarize_prize([], "$750") == "$750"


def test_empty_breakdown_and_no_prize_text_returns_none():
    assert summarize_prize([], None) is None


def test_indian_rupee_symbol_parses():
    result = summarize_prize(["1st: ₹50,000"], None)
    assert result == "Prize pool ₹50,000 (~$600)"


def test_currency_code_prefix_parses():
    result = summarize_prize(["1st: USD 500"], None)
    assert result == "Prize pool USD500"


def test_currency_code_suffix_parses():
    result = summarize_prize(["1st: 500 USD"], None)
    assert result == "Prize pool USD500"


def test_does_not_convert_currencies():
    # Two different currencies must never be summed into one number.
    result = summarize_prize(["1st: $500", "2nd: ₹50,000"], None)
    assert "550" not in result
    assert result == "2 prizes"


# --- USD estimate suffix ---------------------------------------------

def test_bare_non_usd_prize_text_gets_usd_suffix():
    result = summarize_prize([], "₹40,00,000")
    assert result == "₹40,00,000 (~$48,000)"


def test_bare_usd_prize_text_gets_no_suffix():
    result = summarize_prize([], "$175,000")
    assert result == "$175,000"


def test_already_usd_coded_prize_text_gets_no_suffix():
    result = summarize_prize([], "USD 1,050.46")
    assert result == "USD 1,050.46"


def test_free_form_multi_prize_text_gets_no_suffix():
    # A number embedded in a longer sentence — converting the wrong
    # figure would be misleading, so no suffix is added at all.
    text = "First Prize: £500 + 50 credits Second Prize: £300"
    assert summarize_prize([], text) == text


def test_unknown_currency_code_gets_no_suffix_no_crash():
    result = summarize_prize([], "CHF 1,000")
    assert result == "CHF 1,000"
