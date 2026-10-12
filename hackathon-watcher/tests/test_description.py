from __future__ import annotations

from pipeline.description import clean_text, split_sentences, summarize


# --- the reported bug: posts ending on a cut-off clause --------------------

def test_drops_trailing_cut_off_sentence_with_ellipsis():
    text = ("CodeRED: Orion challenges hackers to build something new. "
            "Teams get mentorship from industry engineers. "
            "This Hackathon also provides 6 workshops, held by…")
    assert summarize(text) == (
        "CodeRED: Orion challenges hackers to build something new. "
        "Teams get mentorship from industry engineers."
    )


def test_drops_trailing_mid_word_slice():
    # generic_enrich hard-slices at 500 chars, mid-word.
    text = "Build tools for open finance. Prizes for the top three teams. Judges will lea"
    assert summarize(text) == "Build tools for open finance. Prizes for the top three teams."


def test_never_appends_an_ellipsis():
    out = summarize("One complete sentence. And a half sente…")
    assert out == "One complete sentence."
    assert "…" not in out and "..." not in out


def test_single_cut_sentence_trims_back_to_last_clause():
    text = "This Hackathon also provides 6 workshops, held by…"
    assert summarize(text) == "This Hackathon also provides 6 workshops."


def test_single_cut_sentence_too_short_to_rescue_is_dropped():
    assert summarize("Join us, held by…") is None


def test_tagline_without_period_is_kept_as_written():
    assert summarize("Build AI agents for finance") == "Build AI agents for finance"


def test_three_sentence_cap_kept():
    text = "One. Two here. Three here. Four here."
    assert summarize(text, max_sentences=3) == "One. Two here. Three here."


def test_max_chars_drops_whole_sentences_only():
    text = "Short one. This second sentence is considerably longer than the first."
    assert summarize(text, max_chars=20) == "Short one."


def test_genuine_ellipsis_inside_text_is_preserved():
    text = "Ready... set... hack! Prizes for everyone."
    assert summarize(text) == "Ready... set... hack! Prizes for everyone."


# --- sentence splitting ---------------------------------------------------

def test_abbreviations_do_not_split():
    text = "Use any stack, e.g. Python or Rust. Open to U.S. students only."
    assert split_sentences(text) == [
        "Use any stack, e.g. Python or Rust.",
        "Open to U.S. students only.",
    ]


def test_decimals_and_versions_do_not_split():
    assert split_sentences("Win $2.5k with v1.0 builds. Next.") == ["Win $2.5k with v1.0 builds.", "Next."]


# --- formatting cleanup ---------------------------------------------------

def test_cleanup_collapses_spaces_and_doubled_punctuation():
    assert clean_text("Hello  world ,, again..  Done !") == "Hello world, again. Done!"


def test_cleanup_unescapes_entities_and_strips_artifacts():
    assert clean_text("Tom &amp; Jerry hack. Read more") == "Tom & Jerry hack."
    assert clean_text("Great event. [...]") == "Great event."


def test_cleanup_runaway_dots_become_one_ellipsis():
    assert clean_text("Wait.... what") == "Wait... what"


def test_empty_inputs():
    assert summarize(None) is None
    assert summarize("   ") is None
