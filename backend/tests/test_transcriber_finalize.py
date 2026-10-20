"""The transcriber asks Deepgram to finalize after a pause, so a finished sentence isn't
held until the other person also finishes (measured 3.8 s late on the scam call)."""

import asyncio
import json

from websockets.asyncio.server import serve

from pipeline.bus import EventBus
from pipeline.transcriber import DeepgramTranscriber, TranscriberContext
from tests.fakes import pcm


def run_with_server(frames: list[bytes], **kwargs) -> list[str]:
    received: list[str] = []

    async def handler(ws):
        async for msg in ws:
            if isinstance(msg, str):
                received.append(json.loads(msg)["type"])
                if json.loads(msg)["type"] == "CloseStream":
                    await ws.close()
                    return

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            t = DeepgramTranscriber("key", url=f"ws://127.0.0.1:{port}", keepalive_every=5, **kwargs)
            queue: asyncio.Queue = asyncio.Queue()
            for i, f in enumerate(frames):
                queue.put_nowait((i * 0.08, f))
            queue.put_nowait(None)
            await t.run(queue, EventBus(), TranscriberContext(call_id="t", source="replay", realtime=False))

    asyncio.run(main())
    return received


def split(audio: bytes) -> list[bytes]:
    return [audio[i : i + 2560] for i in range(0, len(audio), 2560)]


def test_finalize_sent_once_per_pause_after_speech():
    frames = split(pcm(0.8, -20)) + split(pcm(0.8, -70)) + split(pcm(0.8, -20)) + split(pcm(0.8, -70))
    assert run_with_server(frames).count("Finalize") == 2


def test_no_finalize_for_silence_without_speech():
    assert "Finalize" not in run_with_server(split(pcm(1.6, -70)))


def test_finalize_can_be_turned_off():
    frames = split(pcm(0.8, -20)) + split(pcm(0.8, -70))
    assert "Finalize" not in run_with_server(frames, finalize_after_silence_s=None)
