import pytest

from src.processor.age import parse_min_age


@pytest.mark.parametrize(
    "text, expected",
    [
        # Ranges — lower bound wins, checked before floors.
        ("ages 18-25", 18),
        ("applicants aged 14–18", 14),
        ("Participants 18-25", 18),
        ("от 18 до 25 лет", 18),
        ("18-25 лет", 18),
        # Floors.
        ("18+", 18),
        ("18 or older", 18),
        ("18 years old and above", 18),
        ("at least 18", 18),
        ("minimum age 18", 18),
        ("от 18 лет", 18),
        ("старше 18", 18),
        ("не младше 18", 18),
        ("18 или старше", 18),
        # Words.
        ("adults only", 18),
        ("совершеннолетние", 18),
        # Negative guards — must never match.
        ("Founded in 2018", None),
        ("$18,000 grant", None),
        ("grade 18", None),
        ("class of 2018", None),
        ("since 1998", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_min_age(text, expected):
    assert parse_min_age(text) == expected


def test_out_of_range_returns_none():
    assert parse_min_age("at least 150") is None
    assert parse_min_age("at least 2") is None
