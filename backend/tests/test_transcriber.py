import asyncio
import json
import socket
import struct
from http import HTTPStatus

import pytest
from websockets.asyncio.server import serve

from audio.sources import FRAME_BYTES
from pipeline.bus import EventBus
from pipeline.events import (
    TranscriberStatus,
    TranscriptClosed,
    TranscriptSegment,
    TranscriptUtteranceEnd,
)
from pipeline.transcriber import DeepgramTranscriber, TranscriberContext, parse_deepgram_message
from tests.fakes import results

# --- parse_deepgram_message ---------------------------------------------------------


def test_parse_prefers_punctuated_word_and_keeps_speaker():
    [seg] = parse_deepgram_message(results([("Hello,", 0.1, 0.4, 1), ("there.", 0.5, 0.9, 1)]), 0.0)
    assert isinstance(seg, TranscriptSegment)
    assert [w.text for w in seg.words] == ["Hello,", "there."]
    assert {w.speaker for w in seg.words} == {1}
    assert seg.is_final and not seg.speech_final


def test_parse_falls_back_to_plain_word():
    [seg] = parse_deepgram_message(results([("Hello", 0.1, 0.4, 0)], punctuated=False), 0.0)
    assert seg.words[0].text == "hello"


def test_parse_adds_offset_to_words_and_segment():
    [seg] = parse_deepgram_message(results([("Hi", 0.5, 0.75, 0)], start=0.25, duration=1.0), 10.0)
    assert seg.words[0].start == pytest.approx(10.5)
    assert seg.words[0].end == pytest.approx(10.75)
    assert seg.start == pytest.approx(10.25)
    assert seg.end == pytest.approx(11.25)


def test_parse_ignores_empty_interim():
    assert parse_deepgram_message(results([], is_final=False), 0.0) == []
    assert parse_deepgram_message(results([], is_final=True, speech_final=False), 0.0) == []


def test_parse_keeps_empty_speech_final():
    [seg] = parse_deepgram_message(results([], is_final=True, speech_final=True), 0.0)
    assert seg.words == [] and seg.speech_final


def test_parse_utterance_end():
    assert parse_deepgram_message({"type": "UtteranceEnd", "last_word_end": -1}, 5.0) == []
    [ev] = parse_deepgram_message({"type": "UtteranceEnd", "last_word_end": 2.5}, 5.0)
    assert isinstance(ev, TranscriptUtteranceEnd)
    assert ev.last_word_end == pytest.approx(7.5)


@pytest.mark.parametrize("kind", ["Metadata", "SpeechStarted", "Whatever"])
def test_parse_ignores_other_messages(kind):
    assert parse_deepgram_message({"type": kind}, 0.0) == []


# --- DeepgramTranscriber against a local fake server ----------------------------------

CTX = TranscriberContext(call_id="t", source="replay", realtime=False)


def frame(i: int) -> bytes:
    """A frame whose first two bytes carry its index, so a server can tell which arrived."""
    return struct.pack("<H", i) + b"\x00" * (FRAME_BYTES - 2)


def frame_index(data: bytes) -> int:
    return struct.unpack("<H", data[:2])[0]


async def run_transcriber(tr, feeder, timeout: float = 10.0) -> list:
    """Run `tr` while `feeder(queue)` supplies audio; return every event it published."""
    bus = EventBus()
    sub = bus.subscribe()
    audio: asyncio.Queue = asyncio.Queue()
    await asyncio.wait_for(asyncio.gather(tr.run(audio, bus, CTX), feeder(audio)), timeout)
    bus.close()
    return [e async for e in sub]


def feed(n: int, gap: float = 0.0):
    async def feeder(q: asyncio.Queue) -> None:
        for i in range(n):
            await q.put((i * 0.08, frame(i)))
            if gap:
                await asyncio.sleep(gap)
        await q.put(None)

    return feeder


def statuses(events) -> list[tuple[str, str]]:
    return [(e.state, e.detail) for e in events if isinstance(e, TranscriberStatus)]


def make(port: int, **kw) -> DeepgramTranscriber:
    kw.setdefault("flush_timeout", 2.0)
    return DeepgramTranscriber("test-key", url=f"ws://127.0.0.1:{port}", **kw)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_of(server) -> int:
    return server.sockets[0].getsockname()[1]


def test_happy_path():
    seen = {"frames": [], "auth": None, "texts": []}

    async def handler(ws):
        seen["auth"] = ws.request.headers.get("Authorization")
        async for msg in ws:
            if isinstance(msg, bytes):
                seen["frames"].append(msg)
                if len(seen["frames"]) == 1:
                    await ws.send(json.dumps(results([("Hello", 0.0, 0.3, 0)], is_final=False)))
            else:
                seen["texts"].append(json.loads(msg))
                if msg and json.loads(msg).get("type") == "CloseStream":
                    await ws.send(json.dumps(results([("Hello", 0.0, 0.3, 0)], speech_final=True)))
                    await ws.close()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            return await run_transcriber(make(port_of(server)), feed(4))

    events = asyncio.run(main())
    assert [s[0] for s in statuses(events)] == ["connecting", "live"]
    segs = [e for e in events if isinstance(e, TranscriptSegment)]
    assert [s.is_final for s in segs] == [False, True]
    assert isinstance(events[-1], TranscriptClosed)
    assert len(seen["frames"]) == 4 and all(len(f) == FRAME_BYTES for f in seen["frames"])
    assert seen["auth"] == "Token test-key"
    assert {"type": "CloseStream"} in seen["texts"]


def test_no_key_is_unavailable_and_drains_audio():
    async def main():
        tr = DeepgramTranscriber("")
        bus = EventBus()
        sub = bus.subscribe()
        audio: asyncio.Queue = asyncio.Queue()
        await feed(5)(audio)
        await asyncio.wait_for(tr.run(audio, bus, CTX), 2)
        bus.close()
        return audio.qsize(), [e async for e in sub]

    left, events = asyncio.run(main())
    assert left == 0
    assert statuses(events) == [("unavailable", "no_key")]
    assert isinstance(events[-1], TranscriptClosed)


def test_unreachable_retries_once_then_unavailable():
    port = free_port()
    tr = make(port, connect_timeout=0.5, max_reconnects=1, backoff=(0.01,))
    events = asyncio.run(run_transcriber(tr, feed(3)))
    assert statuses(events) == [("connecting", ""), ("reconnecting", ""), ("unavailable", "unreachable")]
    assert isinstance(events[-1], TranscriptClosed)


def test_http_401_is_not_retried():
    attempts = 0

    def reject(connection, request):
        nonlocal attempts
        attempts += 1
        return connection.respond(HTTPStatus.UNAUTHORIZED, "bad key\n")

    async def handler(ws):  # never reached
        pass

    async def main():
        async with serve(handler, "127.0.0.1", 0, process_request=reject) as server:
            tr = make(port_of(server), max_reconnects=3, backoff=(0.01,))
            return await run_transcriber(tr, feed(3))

    events = asyncio.run(main())
    assert attempts == 1
    assert statuses(events) == [("connecting", ""), ("unavailable", "rejected_401")]
    assert isinstance(events[-1], TranscriptClosed)


def test_dropped_connection_reconnects_and_offsets_times():
    conns: list[list[int]] = []

    async def handler(ws):
        mine: list[int] = []
        conns.append(mine)
        n_conn = len(conns)
        async for msg in ws:
            if isinstance(msg, bytes):
                mine.append(frame_index(msg))
                if len(mine) == 2 and n_conn == 1:
                    await ws.send(json.dumps(results([("One", 0.0, 0.1, 0)], speech_final=True)))
                    await ws.close()
                    return
                if len(mine) == 1 and n_conn == 2:
                    await ws.send(json.dumps(results([("Two", 0.0, 0.1, 0)], speech_final=True)))
            elif json.loads(msg).get("type") == "CloseStream":
                await ws.close()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            tr = make(port_of(server), max_reconnects=3, backoff=(0.05,))
            return await run_transcriber(tr, feed(40, gap=0.02))

    events = asyncio.run(main())
    assert [s[0] for s in statuses(events)] == ["connecting", "live", "reconnecting", "live"]
    assert len(conns) == 2 and conns[1]
    segs = [e for e in events if isinstance(e, TranscriptSegment)]
    assert [s.words[0].text for s in segs] == ["One", "Two"]
    assert segs[0].words[0].start == pytest.approx(0.0)
    first_on_second = conns[1][0]
    assert first_on_second > 1  # audio that arrived during the reconnect was not replayed from 0
    assert segs[1].words[0].start == pytest.approx(first_on_second * 0.08)
    assert segs[1].start == pytest.approx(first_on_second * 0.08)


def test_keepalive_sent_during_silence():
    texts: list[dict] = []

    async def handler(ws):
        async for msg in ws:
            if isinstance(msg, str):
                texts.append(json.loads(msg))
                if texts[-1].get("type") == "CloseStream":
                    await ws.close()

    async def silent(q: asyncio.Queue) -> None:
        await asyncio.sleep(0.35)
        await q.put(None)

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            return await run_transcriber(make(port_of(server), keepalive_every=0.1), silent)

    events = asyncio.run(main())
    assert sum(t == {"type": "KeepAlive"} for t in texts) >= 2
    assert texts[-1] == {"type": "CloseStream"}
    assert isinstance(events[-1], TranscriptClosed)
