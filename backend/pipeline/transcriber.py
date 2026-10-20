"""Transcriber: streams call audio to Deepgram and publishes normalized segments.

Input:  an asyncio.Queue of (t_call_seconds, 80 ms PCM frame) items, `None` = end.
Output: TranscriberStatus, TranscriptSegment, TranscriptUtteranceEnd, and finally
        TranscriptClosed on the bus.

External call rules: connect timeout, KeepAlive during silence, bounded
reconnects with backoff, and an "unavailable" state instead of a crash.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus, WebSocketException

from audio.sources import FRAME_SECONDS, frame_dbfs
from pipeline.bus import EventBus
from pipeline.events import (
    Event,
    TranscriberStatus,
    TranscriptClosed,
    TranscriptSegment,
    TranscriptUtteranceEnd,
    Word,
)
from pipeline.latency import record

log = logging.getLogger("tenor.transcriber")

AudioItem = tuple[float, bytes] | None

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_PARAMS = {
    "model": "nova-3",  # Deepgram's recommendation for multi-speaker audio
    "encoding": "linear16",
    "sample_rate": "16000",
    "channels": "1",
    "interim_results": "true",
    "diarize_model": "latest",  # enables diarization (replaces diarize=true)
    "smart_format": "true",
    "endpointing": "300",
    "utterance_end_ms": "1000",
    "vad_events": "true",
}


@dataclass
class TranscriberContext:
    call_id: str
    source: str
    realtime: bool
    wall_start: float | None = None  # time.monotonic() of the frame at t_call = 0


class Transcriber(Protocol):
    async def run(self, audio: "asyncio.Queue[AudioItem]", bus: EventBus, ctx: TranscriberContext) -> None: ...


def parse_deepgram_message(msg: dict, offset: float) -> list[Event]:
    """Normalize one Deepgram message. `offset` maps connection time to call time."""
    kind = msg.get("type")
    if kind == "Results":
        alternatives = msg.get("channel", {}).get("alternatives") or [{}]
        words = [
            Word(
                text=w.get("punctuated_word") or w.get("word", ""),
                start=offset + float(w["start"]),
                end=offset + float(w["end"]),
                speaker=int(w.get("speaker", 0)),
                confidence=float(w.get("confidence", 0.0)),
            )
            for w in alternatives[0].get("words", [])
        ]
        speech_final = bool(msg.get("speech_final"))
        if not words and not speech_final:
            return []
        start = offset + float(msg.get("start", 0.0))
        return [
            TranscriptSegment(
                words=words,
                is_final=bool(msg.get("is_final")),
                speech_final=speech_final,
                from_finalize=bool(msg.get("from_finalize")),
                start=start,
                end=start + float(msg.get("duration", 0.0)),
            )
        ]
    if kind == "UtteranceEnd":
        last = float(msg.get("last_word_end", -1))
        return [] if last < 0 else [TranscriptUtteranceEnd(last_word_end=offset + last)]
    return []  # Metadata, SpeechStarted, ...


async def drain(audio: "asyncio.Queue[AudioItem]") -> None:
    """Consume and discard audio until the end marker, so the source never stalls."""
    while await audio.get() is not None:
        pass


def record_lag(segment: TranscriptSegment, ctx: TranscriberContext) -> None:
    """Time from the end of the last word's audio to the result arriving."""
    if not ctx.realtime or ctx.wall_start is None or not segment.words:
        return
    lag_ms = (time.monotonic() - (ctx.wall_start + segment.words[-1].end)) * 1000
    stage = "stt.final_lag" if segment.is_final else "stt.partial_lag"
    record(stage, lag_ms, call_id=ctx.call_id, source=ctx.source)


class DeepgramTranscriber:
    def __init__(
        self,
        api_key: str,
        *,
        url: str = DEEPGRAM_URL,
        connect_timeout: float = 5.0,
        keepalive_every: float = 4.0,
        max_reconnects: int = 3,
        backoff: tuple[float, ...] = (0.5, 1.0, 2.0),
        flush_timeout: float = 2.0,
        finalize_after_silence_s: float | None = 0.45,
        speech_dbfs: float = -45.0,
    ) -> None:
        self.api_key = api_key
        self.url = f"{url}?{urlencode(DEEPGRAM_PARAMS)}"
        self.connect_timeout = connect_timeout
        self.keepalive_every = keepalive_every
        self.max_reconnects = max_reconnects
        self.backoff = backoff
        self.flush_timeout = flush_timeout
        # Deepgram sometimes holds a finished sentence until the *other* person has also
        # finished (one final segment spanning both turns: 3.8 s late on the scam call).
        # So after this much silence following speech, we ask it to finalize now.
        self.finalize_after_silence_s = finalize_after_silence_s
        self.speech_dbfs = speech_dbfs

    async def run(self, audio: "asyncio.Queue[AudioItem]", bus: EventBus, ctx: TranscriberContext) -> None:
        try:
            await self._run(audio, bus, ctx)
        finally:
            bus.publish(TranscriptClosed())

    async def _run(self, audio: "asyncio.Queue[AudioItem]", bus: EventBus, ctx: TranscriberContext) -> None:
        if not self.api_key:
            bus.publish(TranscriberStatus(state="unavailable", detail="no_key"))
            await drain(audio)
            return

        failures = 0
        while True:
            bus.publish(TranscriberStatus(state="connecting" if failures == 0 else "reconnecting"))
            started = time.perf_counter()
            try:
                ws = await connect(
                    self.url,
                    additional_headers={"Authorization": f"Token {self.api_key}"},
                    open_timeout=self.connect_timeout,
                    max_size=None,
                )
            except InvalidStatus as e:
                # 401/403 etc.: retrying with the same key won't help.
                log.warning("deepgram rejected the connection: HTTP %s", e.response.status_code)
                bus.publish(TranscriberStatus(state="unavailable", detail=f"rejected_{e.response.status_code}"))
                await drain(audio)
                return
            except (OSError, TimeoutError, WebSocketException) as e:
                log.warning("deepgram connect failed: %r", e)
                failures += 1
                if failures > self.max_reconnects:
                    bus.publish(TranscriberStatus(state="unavailable", detail="unreachable"))
                    await drain(audio)
                    return
                await asyncio.sleep(self.backoff[min(failures - 1, len(self.backoff) - 1)])
                continue

            record("stt.connect", (time.perf_counter() - started) * 1000, call_id=ctx.call_id, source=ctx.source)
            bus.publish(TranscriberStatus(state="live"))
            outcome, got_results = await self._stream(ws, audio, bus, ctx)
            if outcome == "eof":
                return
            # The connection dropped mid-call. Audio keeps queuing (bounded) while we reconnect.
            failures = 1 if got_results else failures + 1
            if failures > self.max_reconnects:
                bus.publish(TranscriberStatus(state="unavailable", detail="dropped"))
                await drain(audio)
                return
            await asyncio.sleep(self.backoff[min(failures - 1, len(self.backoff) - 1)])

    async def _stream(
        self,
        ws: ClientConnection,
        audio: "asyncio.Queue[AudioItem]",
        bus: EventBus,
        ctx: TranscriberContext,
    ) -> tuple[Literal["eof", "dropped"], bool]:
        offset: float | None = None  # call time of the first frame sent on this connection
        got_results = False
        eof_seen = False  # the end marker was taken off the queue; never wait for audio again

        async def sender() -> Literal["eof"]:
            nonlocal offset, eof_seen
            heard_speech, silent_s = False, 0.0
            while True:
                try:
                    item = await asyncio.wait_for(audio.get(), timeout=self.keepalive_every)
                except TimeoutError:
                    await ws.send(json.dumps({"type": "KeepAlive"}))
                    continue
                if item is None:
                    eof_seen = True
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    return "eof"
                t_call, frame = item
                if offset is None:
                    offset = t_call
                await ws.send(frame)
                if self.finalize_after_silence_s is not None:
                    if frame_dbfs(frame) > self.speech_dbfs:
                        heard_speech, silent_s = True, 0.0
                    elif heard_speech:
                        silent_s += FRAME_SECONDS
                        if silent_s >= self.finalize_after_silence_s:
                            heard_speech = False  # once per pause
                            await ws.send(json.dumps({"type": "Finalize"}))

        async def receiver() -> None:
            nonlocal got_results
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                for event in parse_deepgram_message(json.loads(raw), offset or 0.0):
                    if isinstance(event, TranscriptSegment):
                        got_results = True
                        record_lag(event, ctx)
                    bus.publish(event)

        send_task = asyncio.create_task(sender())
        recv_task = asyncio.create_task(receiver())
        try:
            await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
            if send_task.done() and not send_task.cancelled() and send_task.exception() is None:
                # End of audio: give Deepgram a moment to flush the last results. A fast
                # replay sends audio quicker than real time, so the backlog takes longer.
                flush = self.flush_timeout if ctx.realtime else max(self.flush_timeout, 20.0)
                try:
                    await asyncio.wait_for(asyncio.shield(recv_task), flush)
                except TimeoutError:
                    log.warning("deepgram flush timed out after %.1f s", flush)
                return "eof", got_results
            if eof_seen:
                return "eof", got_results
            log.warning("deepgram connection dropped")
            return "dropped", got_results
        finally:
            for task in (send_task, recv_task):
                task.cancel()
            await asyncio.gather(send_task, recv_task, return_exceptions=True)
            await ws.close()
