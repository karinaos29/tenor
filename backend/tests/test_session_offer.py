"""CallSession wiring: extractor + offer tracker are in the pipeline and drain before call.ended."""

import asyncio

from audio.sources import FileSource
from pipeline.session import CallSession
from tests.fakes import FakeTranscriber, results, write_wav

# Speaker 0 talks first (the user); speaker 1 is the caller.
USER = [("Hello?", 0.0, 0.4, 0)]
SHARES = [("The", 1.0, 1.1, 1), ("shares", 1.1, 1.4, 1), ("are", 1.4, 1.5, 1), ("42", 1.5, 1.8, 1), ("cents", 1.8, 2.1, 1), ("each.", 2.1, 2.4, 1)]
FIVE = [("Start", 3.0, 3.2, 1), ("with", 3.2, 3.4, 1), ("5,000", 3.4, 3.9, 1), ("shares.", 3.9, 4.3, 1)]
TEN = [("Actually", 5.0, 5.4, 1), ("start", 5.4, 5.6, 1), ("with", 5.6, 5.8, 1), ("10,000", 5.8, 6.3, 1), ("shares.", 6.3, 6.7, 1)]


def run_session(tmp_path, script):
    wav = write_wav(tmp_path / "call.wav", 1.0)
    sent = []

    async def send(event):
        sent.append(event)

    session = CallSession(FileSource(wav, realtime=False), FakeTranscriber(script), send, replay_id="call")
    asyncio.run(asyncio.wait_for(session.run(), 20))
    return sent


def test_offer_events_are_forwarded_and_call_ended_is_last(tmp_path):
    sent = run_session(
        tmp_path,
        {
            1: [results(USER, speech_final=True)],
            2: [results(SHARES, speech_final=True)],
            3: [results(FIVE, speech_final=True)],
            4: [results(TEN, speech_final=True)],
        },
    )
    kinds = [e.type for e in sent]
    assert kinds[-1] == "call.ended" and kinds.count("call.ended") == 1
    updates = [e for e in sent if e.type == "offer.updated"]
    assert len(updates) == 3  # price; quantity (+ total); quantity change (+ total)
    assert updates[0].offer.price.display == "$0.42 a share"
    final = updates[-1].offer
    assert final.quantity.display == "10,000 shares" and final.total.display == "$4,200"

    changes = [e.change for e in sent if e.type == "offer.changed"]
    assert [(c.field, c.old.display, c.new.display) for c in changes] == [
        ("quantity", "5,000 shares", "10,000 shares"),
        ("total", "$2,100", "$4,200"),
    ]
    # Every offer event precedes call.ended.
    assert max(i for i, k in enumerate(kinds) if k.startswith("offer.")) < kinds.index("call.ended")


def test_no_offer_change_when_the_quantity_is_repeated(tmp_path):
    sent = run_session(tmp_path, {1: [results(USER, speech_final=True)], 2: [results(FIVE, speech_final=True)]})
    assert [e for e in sent if e.type == "offer.changed"] == []
    assert [e for e in sent if e.type == "offer.updated"][-1].offer.quantity.display == "5,000 shares"
    assert sent[-1].type == "call.ended"


def test_user_lines_do_not_fill_the_offer(tmp_path):
    talk = [("5,000", 0.0, 0.5, 0), ("shares", 0.5, 0.9, 0)]
    sent = run_session(tmp_path, {1: [results(talk, speech_final=True)]})
    assert [e for e in sent if e.type == "offer.updated"] == []
    assert sent[-1].type == "call.ended"
