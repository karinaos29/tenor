"""Voice mode: after a voice check, the labeler tells "You" from "Caller" by voice print.

A stand-in printer maps audio to a print by its sign: positive samples are the user's
voice, negative ones the caller's. Deepgram hears one speaker for everything, as it did on
the live speakerphone test.
"""

import asyncio
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from audio.sources import FRAME_SECONDS, SAMPLE_RATE
from pipeline.bus import EventBus
from pipeline.events import AudioFrame, AudioLevel, SpeakersSwap, SpeakersUpdated, TranscriptClosed, UtteranceFinal
from pipeline.speakers import VOICE_CALLER, VOICE_USER, SpeakerLabeler
from pipeline.transcriber import parse_deepgram_message
from tests.fakes import FakeTranscriber, results

USER, CALLER = 1, -1  # sample sign of each voice


class SignPrinter:
    """Prints [1, 0] for the user's audio and [0.6, 0.8] (similarity 0.6) for the caller's."""

    calls = 0

    def embed(self, samples: np.ndarray) -> np.ndarray:
        SignPrinter.calls += 1
        return np.array([1.0, 0.0]) if samples.mean() > 0 else np.array([0.6, 0.8])


ENROLLED = np.array([1.0, 0.0])


class Harness:
    def __init__(self, user_print=ENROLLED) -> None:
        self.bus = EventBus()
        self.out = self.bus.subscribe(UtteranceFinal, SpeakersUpdated)
        self.labeler = SpeakerLabeler(self.bus, printer=SignPrinter(), user_print=user_print)
        self.t = 0.0

    def audio(self, t0: float, t1: float, who: int, dbfs: float) -> None:
        i = round(t0 / FRAME_SECONDS)
        frame = np.full(int(FRAME_SECONDS * SAMPLE_RATE), who * 3000, dtype="<i2").tobytes()
        while i * FRAME_SECONDS < t1 - 1e-9:
            self.bus.publish(AudioLevel(t=i * FRAME_SECONDS, dbfs=dbfs))
            self.bus.publish(AudioFrame(t=i * FRAME_SECONDS, pcm=frame))
            i += 1

    def segment(self, stretches: list[tuple[int, float, float]]) -> None:
        """One final Deepgram segment, all words speaker 0: (who, seconds, dbfs) per stretch,
        each followed by a 0.4 s pause."""
        words = []
        for k, (who, seconds, dbfs) in enumerate(stretches):
            n = max(1, round(seconds / 0.3))
            words += [(f"s{k}w{i}", self.t + 0.3 * i, self.t + 0.3 * (i + 1), 0) for i in range(n)]
            self.audio(self.t, self.t + 0.3 * n, who, dbfs)
            self.audio(self.t + 0.3 * n, self.t + 0.3 * n + 0.4, who, -60.0)
            self.t += 0.3 * n + 0.4
        for e in parse_deepgram_message(results(words, True, True), 0.0):
            self.bus.publish(e)


def run(scenario, **kw) -> list:
    async def main():
        h = Harness(**kw)
        task = asyncio.create_task(h.labeler.run())
        await asyncio.sleep(0)
        await scenario(h)
        h.bus.publish(TranscriptClosed())
        await asyncio.wait_for(task, 2)
        h.bus.close()
        return [e async for e in h.out]

    return asyncio.run(main())


def roles(events) -> list[tuple[str, int]]:
    return [(e.utterance.speaker, e.utterance.speaker_index) for e in events if isinstance(e, UtteranceFinal)]


def test_one_deepgram_speaker_is_told_apart_by_voice():
    async def scenario(h):
        h.segment([(CALLER, 2.4, -20), (USER, 1.5, -26)])
        await asyncio.sleep(0.05)
        h.segment([(CALLER, 2.1, -20), (USER, 1.2, -26), (CALLER, 1.8, -20)])
        await asyncio.sleep(0.05)

    events = run(scenario)
    first = [e for e in events if isinstance(e, SpeakersUpdated)][0]
    assert (first.user_indices, first.reason) == ([VOICE_USER], "voice")
    assert roles(events) == [
        ("caller", VOICE_CALLER), ("user", VOICE_USER), ("caller", VOICE_CALLER), ("user", VOICE_USER), ("caller", VOICE_CALLER),
    ]  # fmt: skip


def test_a_short_reply_falls_back_to_the_nearer_loudness():
    async def scenario(h):
        h.segment([(CALLER, 2.4, -20), (USER, 1.5, -30), (CALLER, 2.4, -20)])
        await asyncio.sleep(0.05)
        h.segment([(USER, 0.3, -30)])  # "Yes." - too short for a print
        await asyncio.sleep(0.05)

    assert roles(run(scenario))[-1] == ("user", VOICE_USER)


def test_swap_still_wins_in_voice_mode():
    async def scenario(h):
        h.segment([(USER, 1.5, -20)])
        await asyncio.sleep(0.05)
        h.bus.publish(SpeakersSwap())
        await asyncio.sleep(0.05)

    last = [e for e in run(scenario) if isinstance(e, SpeakersUpdated)][-1]
    assert (last.user_indices, last.reason, last.locked) == ([VOICE_CALLER], "manual", True)


# --- the API ------------------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture
def printer():
    old = app.state.printer
    app.state.printer = SignPrinter()
    yield
    app.state.printer = old


def speech(seconds: float, who: int = USER) -> bytes:
    return np.full(int(seconds * SAMPLE_RATE), who * 3000, dtype="<i2").tobytes()


@pytest.mark.usefixtures("printer")
def test_voice_check_returns_an_id_and_keeps_the_print():
    body = client.post("/api/voice", content=speech(3.0), headers={"Content-Type": "application/octet-stream"}).json()
    assert body["ok"] is True and body["message"] == "Tenor knows your voice."
    assert np.allclose(app.state.voices[body["voice_id"]], ENROLLED)


@pytest.mark.usefixtures("printer")
def test_voice_check_needs_enough_speech():
    quiet = np.zeros(SAMPLE_RATE * 3, dtype="<i2").tobytes()
    body = client.post("/api/voice", content=quiet).json()
    assert body["ok"] is False and "full sentence" in body["message"]


def test_voice_check_without_the_model_says_so():
    old, app.state.printer = app.state.printer, None
    try:
        body = client.post("/api/voice", content=speech(3.0)).json()
    finally:
        app.state.printer = old
    assert body["ok"] is False and body["voice_id"] is None


@pytest.mark.usefixtures("printer")
def test_a_live_call_with_a_voice_id_runs_in_voice_mode():
    voice_id = client.post("/api/voice", content=speech(3.0)).json()["voice_id"]
    old_factory = app.state.transcriber_factory
    app.state.transcriber_factory = lambda: FakeTranscriber()
    try:
        with client.websocket_connect("/ws/call") as ws:
            ws.send_text(json.dumps({"type": "call.start", "source": "mic", "voice_id": voice_id}))
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "speakers.updated":
                    break
            ws.send_text(json.dumps({"type": "call.stop"}))
    finally:
        app.state.transcriber_factory = old_factory
    assert msg["reason"] == "voice" and msg["user_indices"] == [VOICE_USER]
