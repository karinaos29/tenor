"""Regression tests from real Deepgram output (honest_voo / scam_kstl replays, 2026-10-20)."""

from pipeline.extractor import extract_rules
from providers.catalog import default_catalog


def entities(text: str, kind: str) -> list:
    return [e for e in extract_rules(text, default_catalog()).entities if e.kind == kind]


def test_dropped_decimal_point_in_percent():
    # "a quarter percent a year" came back as "025%".
    fees = entities("Our platform fee is 025% a year.", "fee")
    assert [f.value for f in fees] == ["0.25% a year"]
    assert fees[0].number == 0.25


def test_ordinary_percents_unchanged():
    assert entities("the stock is up 40% this quarter", "percent")[0].number == 40
    assert entities("a fee of 0.5% a year", "percent")[0].number == 0.5


def test_full_name_beats_misheard_greeting():
    # "Hello, is this Eszter?" was heard as "Hello. This is Esther."
    text = "Hello. This is Esther. This is Tom Becker from Riverside Savings Management."
    assert [p.value for p in entities(text, "person")] == ["Tom Becker"]


def test_my_name_is_beats_this_is():
    text = "This is Hartley speaking. My name is Daniel Reeves."
    assert [p.value for p in entities(text, "person")] == ["Daniel Reeves"]


def test_deepgram_formats_from_scam_replay():
    assert entities("Right now, the shares are 42¢ each.", "price")[0].value == "$0.42 a share"
    assert entities("this price is only locked until 3PM today.", "deadline")[0].value == "Today, 3:00 PM"
    assert entities("We have a rare opportunity on a company called Kestrel Motors. Ticker KSTL.", "ticker")[0].value == "KSTL"
    assert entities("The ticker is v o o.", "ticker")[0].value == "VOO"
