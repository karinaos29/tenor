"""Spoken numbers -> digits, with spans that map back to the original words."""

import pytest

from pipeline.numbers import normalize


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("forty-two cents", "42 cents"),
        ("forty two cents", "42 cents"),
        ("ten thousand shares", "10000 shares"),
        ("twenty-one hundred dollars", "2100 dollars"),
        ("one hundred and fifty dollars", "150 dollars"),
        ("five and six", "5 and 6"),  # "and" only joins after a scale word
        ("a thousand shares", "1000 shares"),
        ("a hundred dollars", "100 dollars"),
        ("on April fifteenth", "on April 15"),
        ("a quarter percent a year", "0.25 percent a year"),
        ("half a percent", "0.5 percent"),
        ("three hundredths of a percent", "0.03 percent"),
        ("two tenths of a percent", "0.2 percent"),
        ("five thousand shares at forty-two cents", "5000 shares at 42 cents"),
    ],
)
def test_words_become_digits(spoken, expected):
    assert normalize(spoken).text == expected


@pytest.mark.parametrize("text", ["10,000 shares", "$0.42 a share", "3PM today", "April 15th", "42¢ each", "no numbers here"])
def test_digits_pass_through_untouched(text):
    assert normalize(text).text == text


def test_five_and_six_stays_two_numbers():
    assert normalize("five and six").text.split() == ["5", "and", "6"]


def test_original_span_maps_back_to_exact_words():
    text = "the shares are forty-two cents each"
    norm = normalize(text)
    start = norm.text.index("42")
    assert text[slice(*norm.original_span(start, start + 2))] == "forty-two"
    start = norm.text.index("42 cents")
    assert text[slice(*norm.original_span(start, start + len("42 cents")))] == "forty-two cents"


def test_original_span_for_multiword_number_and_fraction():
    text = "start with ten thousand shares"
    norm = normalize(text)
    start = norm.text.index("10000 shares")
    a, b = norm.original_span(start, start + len("10000 shares"))
    assert text[a:b] == "ten thousand shares"

    text = "our fee is a quarter percent a year"
    norm = normalize(text)
    start = norm.text.index("0.25 percent")
    a, b = norm.original_span(start, start + len("0.25 percent"))
    assert text[a:b] == "a quarter percent"

    text = "it is three hundredths of a percent"
    norm = normalize(text)
    start = norm.text.index("0.03 percent")
    a, b = norm.original_span(start, start + len("0.03 percent"))
    assert text[a:b] == "three hundredths of a percent"


def test_original_span_for_ordinal_and_digits():
    text = "the deadline is April fifteenth."
    norm = normalize(text)
    start = norm.text.index("15")
    assert text[slice(*norm.original_span(start, start + 2))] == "fifteenth"
    plain = normalize("keep 10,000 as is")
    assert plain.original_span(5, 11) == (5, 11)
