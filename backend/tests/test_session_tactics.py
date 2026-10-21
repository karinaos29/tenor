"""CallSession wiring for M4: tactic flags reach the browser and call.ended is still last."""

import asyncio

from audio.sources import FileSource
from detector.taxonomy import BY_ID
from pipeline.session import CallSession
from tests.fakes import FakeTranscriber, results, write_wav
from tests.test_session_offer import USER
from tests.test_session_verify import W


class FakeClassifier:
    thresholds = {t: 0.5 for t in BY_ID}

    def predict_proba(self, texts):
        return [{**{t: 0.0 for t in BY_ID}, "secrecy": 0.95 if "quiet" in x else 0.0} for x in texts]


def run(tmp_path, script, classifier):
    wav = write_wav(tmp_path / "call.wav", 1.0)
    sent = []

    async def send(event):
        sent.append(event)

    session = CallSession(FileSource(wav, realtime=False), FakeTranscriber(script), send, replay_id="call", classifier=classifier)
    asyncio.run(asyncio.wait_for(session.run(), 20))
    return sent


def test_classifier_flag_is_forwarded_and_call_ended_is_last(tmp_path):
    caller = W("This stays quiet here.", 1.0)
    sent = run(tmp_path, {1: [results(USER, speech_final=True)], 2: [results(caller, speech_final=True)]}, FakeClassifier())
    kinds = [e.type for e in sent]
    assert kinds[-1] == "call.ended" and kinds.count("call.ended") == 1
    flags = [e.flag for e in sent if e.type == "tactic.flagged"]
    assert [(f.tactic, f.source) for f in flags] == [("secrecy", "classifier")]
    assert max(i for i, k in enumerate(kinds) if k == "tactic.flagged") < kinds.index("call.ended")
    assert "tactics.closed" not in kinds
    assert [e for e in sent if e.type == "risk.updated"][-1].score == 15


def test_user_line_is_not_flagged(tmp_path):
    user = [(w, t, e, 0) for w, t, e, _ in W("This stays quiet here.", 0.0)]
    caller = W("Thank you.", 3.0)
    sent = run(tmp_path, {1: [results(user, speech_final=True)], 2: [results(caller, speech_final=True)]}, FakeClassifier())
    assert [e for e in sent if e.type == "tactic.flagged"] == []
    assert sent[-1].type == "call.ended"
