"""Real Deepgram round trip. Excluded by default; run with `uv run pytest -m deepgram -q`."""

import asyncio
from pathlib import Path

import pytest

from app.config import get_settings
from audio.sources import FileSource
from pipeline.events import UtteranceFinal
from pipeline.session import CallSession
from pipeline.transcriber import DeepgramTranscriber

CLIP = Path(__file__).resolve().parents[1] / "fixtures" / "calls" / "m1_hello.wav"


@pytest.mark.deepgram
def test_m1_hello_through_real_deepgram():
    key = get_settings().deepgram_api_key
    if not key:
        pytest.skip("DEEPGRAM_API_KEY not set")

    async def main():
        sent = []

        async def send(event):
            sent.append(event)

        session = CallSession(FileSource(CLIP, realtime=True), DeepgramTranscriber(key), send, replay_id="m1_hello")
        await asyncio.wait_for(session.run(), 120)
        return sent

    events = asyncio.run(main())
    finals = [e.utterance for e in events if isinstance(e, UtteranceFinal)]
    assert len(finals) >= 5, [u.text for u in finals]
    assert {u.speaker for u in finals} == {"user", "caller"}
    assert finals[0].speaker == "user"
    assert any("kestrel" in u.text.lower() for u in finals if u.speaker == "caller"), [
        (u.speaker, u.text) for u in finals
    ]
    assert events[-1].type == "call.ended" and events[-1].reason == "replay_finished"


SCAM = Path(__file__).resolve().parents[1] / "fixtures" / "calls" / "scam_kstl.wav"


@pytest.mark.deepgram
def test_scam_kstl_offer_through_real_deepgram():
    """Real-time replay of the scripted scam call: speech-to-text must feed the offer tracker correctly."""
    import json

    key = get_settings().deepgram_api_key
    if not key:
        pytest.skip("DEEPGRAM_API_KEY not set")
    if not SCAM.exists():
        pytest.skip("fixtures/calls/scam_kstl.wav not generated")
    want = json.loads((SCAM.parent / "expected" / "scam_kstl.json").read_text())["offer"]

    async def main():
        sent = []

        async def send(event):
            sent.append(event)

        session = CallSession(FileSource(SCAM, realtime=True), DeepgramTranscriber(key), send, replay_id="scam_kstl")
        await asyncio.wait_for(session.run(), 300)
        return sent

    events = asyncio.run(main())
    assert events[-1].type == "call.ended"
    offer = [e for e in events if e.type == "offer.updated"][-1].offer
    assert offer.instrument.display == want["instrument"]
    assert offer.price.display == want["price"]
    assert offer.quantity.display == want["quantity"]
    assert offer.deadline.display == want["deadline"]
