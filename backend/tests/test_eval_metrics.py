"""Evaluation metrics and expectation parsing from eval/run_eval.py."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval as ev  # noqa: E402

from detector.taxonomy import TACTIC_IDS  # noqa: E402

TRUTH = [{"urgency"}, {"secrecy", "guarantee"}, set(), {"urgency"}]


def test_perfect_predictions():
    assert ev.scores(TRUTH, TRUTH, "urgency") == (1.0, 1.0, 1.0, 2)
    assert ev.micro(TRUTH, TRUTH) == (1.0, 1.0, 1.0, 4)
    assert ev.scores(TRUTH, TRUTH, None) == (1.0, 1.0, 1.0, 3)


def test_all_wrong():
    pred = [{"scarcity"}, {"authority"}, {"fomo_regret"}, {"authority"}]
    assert ev.scores(TRUTH, pred, "urgency") == (0.0, 0.0, 0.0, 2)
    assert ev.micro(TRUTH, pred) == (0.0, 0.0, 0.0, 4)


def test_empty_predictions():
    pred = [set() for _ in TRUTH]
    assert ev.scores(TRUTH, pred, "urgency") == (0.0, 0.0, 0.0, 2)
    assert ev.micro(TRUTH, pred) == (0.0, 0.0, 0.0, 4)
    assert ev.scores(TRUTH, pred, None) == (0.0, 0.0, 0.0, 3)


def test_partial_scores():
    pred = [{"urgency"}, {"secrecy"}, {"urgency"}, set()]
    assert ev.scores(TRUTH, pred, "urgency") == (0.5, 0.5, 0.5, 2)
    p, r, f, n = ev.micro(TRUTH, pred)
    assert (p, r, n) == (0.667, 0.5, 4) and f == 0.571


def test_any_tactic_mode_ignores_which_tactic():
    pred = [{"scarcity"}, {"authority"}, {"urgency"}, set()]
    assert ev.scores(TRUTH, pred, None) == (0.667, 0.667, 0.667, 3)


def test_detector_scores_has_all_rows():
    d = ev.detector_scores("X", TRUTH, TRUTH, 1.234, "note")
    assert [r.tactic for r in d.rows] == list(TACTIC_IDS) and len(d.rows) == 8
    assert d.micro.tactic == "micro" and d.micro.f1 == 1.0 and d.micro.support == 4
    assert d.any_tactic.tactic == "any" and d.any_tactic.support == 3
    assert d.latency_ms_median == 1.23 and d.note == "note" and d.name == "X"
    assert {r.tactic: r.support for r in d.rows}["urgency"] == 2


def test_expectation_m4_manipulative_and_honest():
    assert ev.expectation("anything", {"kind": "manipulative", "risk": {"min_level": "critical"}}) == ("manipulative", "critical or above", "critical", None)
    assert ev.expectation("anything", {"kind": "honest", "risk": {"max_level": "low"}}) == ("honest", "low or below", None, "low")


def test_expectation_defaults():
    assert ev.expectation("x", {"kind": "manipulative"})[2] == "high"
    assert ev.expectation("x", {"kind": "honest"})[3] == "medium"


@pytest.mark.parametrize("name,kind", [("scam_kstl", "manipulative"), ("honest_voo", "honest"), ("whatever", "honest")])
def test_expectation_old_format_kind_from_name(name, kind):
    assert ev.expectation(name, {"risk": {}})[0] == kind
    assert ev.expectation(name, {})[0] == kind


def test_expectation_old_format_levels():
    assert ev.expectation("scam_x", {"risk": {"min_level": "critical"}}) == ("manipulative", "critical or above", "critical", None)
    assert ev.expectation("honest_x", {"risk": {"max_level": "low"}}) == ("honest", "low or below", None, "low")
