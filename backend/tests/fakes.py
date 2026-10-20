"""Shared test helpers: synthetic audio, Deepgram message builders, a fake transcriber."""

import asyncio
import math
import struct
import wave
from pathlib import Path

import numpy as np

from audio.sources import SAMPLE_RATE
from pipeline.bus import EventBus
from pipeline.events import TranscriberStatus, TranscriptClosed
from pipeline.transcriber import AudioItem, TranscriberContext, parse_deepgram_message


def pcm(seconds: float, dbfs: float = -20.0) -> bytes:
    """16 kHz mono int16 little-endian sine whose RMS is `dbfs` (0 = full-scale RMS)."""
    n = round(seconds * SAMPLE_RATE)
    rms = 32768 * 10 ** (dbfs / 20)
    amp = min(rms * math.sqrt(2), 32767)
    t = np.arange(n) / SAMPLE_RATE
    return np.round(amp * np.sin(2 * np.pi * 440 * t)).astype("<i2").tobytes()


def write_wav(path: Path, seconds: float, dbfs: float = -20.0, *, rate: int = SAMPLE_RATE, channels: int = 1) -> Path:
    data = pcm(seconds, dbfs)
    if rate != SAMPLE_RATE:
        data = pcm(seconds, dbfs)  # content is irrelevant; only the header matters
    if channels == 2:
        samples = struct.unpack(f"<{len(data) // 2}h", data)
        data = struct.pack(f"<{len(samples) * 2}h", *[s for x in samples for s in (x, x)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)
    return path


Word = tuple[str, float, float, int]  # text, start, end, speaker


def results(
    words: list[Word],
    is_final: bool = True,
    speech_final: bool = False,
    start: float = 0.0,
    duration: float = 1.0,
    *,
    punctuated: bool = True,
) -> dict:
    """A Deepgram streaming "Results" message."""
    out = []
    for text, s, e, spk in words:
        w = {"word": text.lower().strip(".,?!"), "start": s, "end": e, "confidence": 0.9, "speaker": spk}
        if punctuated:
            w["punctuated_word"] = text
        out.append(w)
    return {
        "type": "Results",
        "start": start,
        "duration": duration,
        "is_final": is_final,
        "speech_final": speech_final,
        "channel": {"alternatives": [{"transcript": " ".join(w[0] for w in words), "words": out}]},
    }


class FakeTranscriber:
    """Implements the Transcriber protocol with scripted Deepgram messages.

    `script` maps "after N frames received" -> messages published once N frames were
    consumed. Remaining scripted messages are flushed on the end marker.
    """

    def __init__(self, script: dict[int, list[dict]] | None = None, offset: float = 0.0) -> None:
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.offset = offset
        self.frames_seen = 0

    async def run(self, audio: "asyncio.Queue[AudioItem]", bus: EventBus, ctx: TranscriberContext) -> None:
        try:
            bus.publish(TranscriberStatus(state="live"))
            while True:
                item = await audio.get()
                if item is None:
                    for n in sorted(self.script):
                        self._publish(bus, self.script.pop(n))
                    return
                self.frames_seen += 1
                for n in sorted(k for k in self.script if k <= self.frames_seen):
                    self._publish(bus, self.script.pop(n))
        finally:
            bus.publish(TranscriptClosed())

    def _publish(self, bus: EventBus, messages: list[dict]) -> None:
        for msg in messages:
            for event in parse_deepgram_message(msg, self.offset):
                bus.publish(event)
