"""CallSession: hanging up never waits for the memo; the memo lands in the store afterwards."""

import asyncio

from audio.sources import FileSource
from memo.store import MemoStore
from pipeline.session import CallSession
from tests.fakes import FakeTranscriber, results, write_wav
from tests.m5_helpers import tmp_store
from tests.test_session_offer import USER
from tests.test_session_verify import W


def test_memo_is_written_after_call_ended(tmp_path):
    store = tmp_store(tmp_path)
    caller = W("Keep this quiet. Everyone is doing it, so act now.", 1.0)
    wav = write_wav(tmp_path / "call.wav", 1.0)
    sent, at_end = [], {}

    async def main():
        session = CallSession(
            FileSource(wav, realtime=False), FakeTranscriber({1: [results(USER, speech_final=True)], 2: [results(caller, speech_final=True)]}),
            None, replay_id="call", store=store, memo_llm=None,
        )

        async def send(event):
            sent.append(event)
            if event.type == "call.ended":
                at_end["done"] = session.memo_task.done()
                at_end["status"] = store.get(session.id)[0]

        session.send = send
        await asyncio.wait_for(session.run(), 20)
        assert session.memo_task is not None
        memo = await asyncio.wait_for(session.memo_task, 10)
        return session, memo

    session, memo = asyncio.run(main())
    assert sent[-1].type == "call.ended"
    assert at_end["done"] is False  # call.ended went out before the memo was finished
    assert at_end["status"] in ("live", "writing")
    assert memo is not None and memo.call_id == session.id and memo.summary_wording == "template"
    status, saved = store.get(session.id)
    assert status == "ready" and saved == memo
    assert any(i.source in ("Strong", "Mild") for s in memo.sections if s.id == "pressure" for i in s.items)


def test_session_without_store_still_builds_memo(tmp_path):
    wav = write_wav(tmp_path / "call.wav", 1.0)

    async def main():
        async def send(e):
            pass

        s = CallSession(FileSource(wav, realtime=False), FakeTranscriber({1: [results(USER, speech_final=True)]}), send)
        await asyncio.wait_for(s.run(), 20)
        return await asyncio.wait_for(s.memo_task, 10)

    assert asyncio.run(main()) is not None
