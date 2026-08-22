from __future__ import annotations

from pipeline.normalize import normalized_title


def test_lowercases_and_strips_punctuation():
    assert normalized_title("HackMTY 2026!") == "hackmty"


def test_collapses_whitespace():
    assert normalized_title("  Global   Hack   Week  ") == "global week"


def test_drops_noise_words():
    assert normalized_title("Best Hackathon 2026") == "best"
    assert normalized_title("Hack the North") == "the north"


def test_same_event_different_titles_collide():
    a = normalized_title("Hack The North 2026")
    b = normalized_title("hack the north!")
    assert a == b
