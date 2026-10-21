from datetime import datetime

from memo.builder import build_memo
from tests.m5_helpers import scam_record, tmp_store


def test_lifecycle_and_roundtrip(tmp_path):
    s = tmp_store(tmp_path)
    s.start("c1", "2026-10-01T12:00:00+00:00", "replay", "scam")
    assert s.get("c1") == ("live", None)
    s.set_status("c1", "writing")
    assert s.get("c1") == ("writing", None)
    memo = build_memo(scam_record(), "sum", "template")
    s.save_memo(memo)
    status, got = s.get("c1")
    assert status == "ready" and got == memo


def test_unknown(tmp_path):
    assert tmp_store(tmp_path).get("nope") == ("unknown", None)


def test_recent_order_and_fields(tmp_path):
    s = tmp_store(tmp_path)
    s.start("old", "2026-10-01T10:00:00+00:00", "mic", None)
    s.start("new", "2026-10-02T10:00:00+00:00", "replay", "scam")
    s.save_memo(build_memo(scam_record(), "sum", "template").model_copy(update={"call_id": "new"}))
    rows = s.recent()
    assert [r.call_id for r in rows] == ["new", "old"]
    new, old = rows
    assert (new.status, new.risk_level, new.replay_id, new.source) == ("ready", "critical", "scam", "replay")
    assert new.headline and isinstance(new.started_at, datetime)
    assert (old.status, old.risk_level, old.headline) == ("live", None, None)
    assert len(s.recent(limit=1)) == 1
