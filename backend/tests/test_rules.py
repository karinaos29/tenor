"""Tactic rules: fire on clear examples, stay quiet on the honest look-alikes."""

import pytest

from detector.rules import rule_tactics
from detector.taxonomy import TACTIC_IDS

FIRES = {
    "urgency": ["You must decide now, before we hang up.", "The price is locked only until 3 pm today.", "This offer closes tonight."],
    "scarcity": ["This is a rare opportunity for a few clients.", "Only a handful of places are left.", "It is not offered to the public."],
    "social_proof": ["Most of my clients are taking ten thousand shares.", "Thousands have already joined.", "Everyone is buying this one."],
    "secrecy": ["Keep this between us, please.", "Don't tell your bank about it.", "Families often don't understand these things."],
    "guarantee": ["It's a guaranteed return.", "This one is completely risk-free.", "You can't lose with this."],
    "fomo_regret": ["People who waited regretted it.", "You'll kick yourself later.", "Don't miss out on this."],
    "skip_checks": ["There's no time for paperwork.", "You don't need to read it.", "We can confirm by phone."],
    "authority": ["Our analysts say it will rise.", "Insiders know what is coming.", "It's the next Apple."],
}

HONEST = [
    "Past returns don't guarantee future results.",
    "Nobody can guarantee a share price.",
    "Deposits are insured up to the legal limit.",
    "No rush, take your time.",
    "You won't miss out if you wait.",
    "I can send you the documents to read.",
    "Take your time to read the factsheet.",
    "Feel free to talk it over with your family.",
    "The fund's factsheet lists the fee.",
    "This account has no minimum.",
    "Markets have gone up and down over time.",
    "The deadline is at the end of the tax year, no pressure.",
]


@pytest.mark.parametrize("tactic", TACTIC_IDS)
def test_each_tactic_fires_on_clear_examples(tactic):
    for sentence in FIRES[tactic]:
        assert tactic in rule_tactics(sentence), sentence


def test_every_tactic_is_covered():
    assert set(FIRES) == set(TACTIC_IDS)


@pytest.mark.parametrize("sentence", HONEST)
def test_honest_lookalikes_raise_nothing(sentence):
    assert rule_tactics(sentence) == set()


def test_returns_a_set():
    assert isinstance(rule_tactics("Have a nice afternoon."), set)
    assert rule_tactics("") == set()


def test_multi_tactic_sentence_returns_several():
    hits = rule_tactics("It's guaranteed, so decide now and keep this between us.")
    assert {"guarantee", "urgency", "secrecy"} <= hits


def test_exception_only_cancels_its_own_tactic():
    # "no rush" cancels urgency, but the guarantee in the same sentence still counts.
    hits = rule_tactics("There's no rush, but it's a sure thing.")
    assert "guarantee" in hits and "urgency" not in hits
