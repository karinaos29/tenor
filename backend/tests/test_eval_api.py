"""GET /api/eval: missing, valid and corrupt results files."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from pipeline.events import CallResult, DetectorScores, EvalReport, MetricRow, StageLatency, Target

client = TestClient(app)


@pytest.fixture
def results_path(tmp_path):
    old = app.state.eval_results
    app.state.eval_results = tmp_path / "latest.json"
    yield app.state.eval_results
    app.state.eval_results = old


def row(tactic="micro"):
    return MetricRow(tactic=tactic, label="L", precision=0.9, recall=0.8, f1=0.85, support=10)


def report():
    return EvalReport(
        run_id="abc123", created_at=datetime(2026, 10, 1, tzinfo=UTC), commit="deadbee", note="n", data="d",
        targets=[Target(label="t", target="≥ 0.8", measured="0.9", met=True)],
        detectors=[DetectorScores(name="Rules", rows=[row("urgency")], micro=row(), any_tactic=row("any"), latency_ms_median=0.5, note="")],
        calls=[CallResult(name="scam_x", kind="manipulative", hard_honest=False, expected="high or above", risk_score=80, risk_level="critical",
                          ok=True, false_claims_expected=1, false_claims_caught=1, tactic_recall=1.0, tactic_precision=None, max_visible_suggestions=3)],
        latency=[StageLatency(stage="detector", n=5, median_ms=3.0, p95_ms=9.0)],
        audio=False,
    )  # fmt: skip


def test_missing_file_returns_null(results_path):
    r = client.get("/api/eval")
    assert r.status_code == 200 and r.json() == {"report": None}


def test_valid_report_round_trips(results_path):
    rep = report()
    results_path.write_text(rep.model_dump_json())
    r = client.get("/api/eval")
    assert r.status_code == 200
    assert EvalReport.model_validate(r.json()["report"]) == rep


@pytest.mark.parametrize("text", ["{not json", '{"run_id": "x"}', ""])
def test_corrupt_file_returns_null_not_500(results_path, text):
    results_path.write_text(text)
    r = client.get("/api/eval")
    assert r.status_code == 200 and r.json() == {"report": None}
