"""CallSession wiring for M3: verify events reach the browser and call.ended is still last."""

from tests.fakes import results
from tests.test_session_offer import USER, run_session

W = lambda text, t0, spk=1: [(w, t0 + i * 0.2, t0 + i * 0.2 + 0.15, spk) for i, w in enumerate(text.split())]  # noqa: E731
LINE = W("The ticker is K S T L. The stock is up forty percent this quarter.", 1.0)


def scripted():
    return {1: [results(USER, speech_final=True)], 2: [results(LINE, speech_final=True)]}


def test_verify_events_are_forwarded_and_call_ended_is_last(tmp_path):
    sent = run_session(tmp_path, scripted())
    kinds = [e.type for e in sent]
    assert kinds[-1] == "call.ended" and kinds.count("call.ended") == 1
    for kind in ("claim.checked", "research.ready", "suggestions.updated", "risk.updated"):
        assert kind in kinds, kinds
        assert max(i for i, k in enumerate(kinds) if k == kind) < kinds.index("call.ended")

    claim = [e.claim for e in sent if e.type == "claim.checked"][-1]
    assert claim.metric == "price_change" and claim.subject == "KSTL"
    assert claim.status == "false" and claim.actual_value == -12.5 and claim.note == "last 13 weeks"

    research = {e.item.id: e.item for e in sent if e.type == "research.ready"}
    assert research["r-ticker-kstl"].status == "ready"

    last = [e for e in sent if e.type == "suggestions.updated"][-1]
    assert last.visible[0].id.startswith("say-claim-")
    assert "went down 12.5%" in last.visible[0].text
    assert [e for e in sent if e.type == "risk.updated"][-1].score >= 30


def test_internal_close_events_stay_off_the_wire(tmp_path):
    kinds = {e.type for e in run_session(tmp_path, scripted())}
    assert not {"checks.closed", "research.closed", "entities.closed"} & kinds


def test_quiet_call_publishes_no_risk(tmp_path):
    sent = run_session(tmp_path, {1: [results(USER, speech_final=True)]})
    kinds = [e.type for e in sent]
    assert "risk.updated" not in kinds and kinds[-1] == "call.ended"
