"""Audio sources. Every source yields the same thing: 80 ms frames of 16 kHz mono
16-bit little-endian PCM (1280 samples, 2560 bytes). Everything after the source
is identical for live mic and replay.

Future source (out of scope for the prototype): a telephony stream (e.g. Twilio
Media Streams) would implement the same `AudioSource` protocol.
"""

import asyncio
import logging
import math
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE  # 0.08

log = logging.getLogger("tenor.audio")


class AudioSource(Protocol):
    kind: Literal["mic", "replay"]
    realtime: bool

    def frames(self) -> AsyncIterator[bytes]: ...

    def close(self) -> None: ...


class MicSource:
    """Frames pushed in from the browser over the call WebSocket."""

    kind: Literal["mic", "replay"] = "mic"
    realtime = True

    def __init__(self, max_buffered_frames: int = 125) -> None:  # 10 s
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=max_buffered_frames)
        self._pending = bytearray()
        self._closed = False

    def push(self, data: bytes) -> None:
        """Accept any chunk size; re-chunk into exact 80 ms frames."""
        if self._closed:
            return
        self._pending.extend(data)
        while len(self._pending) >= FRAME_BYTES:
            frame = bytes(self._pending[:FRAME_BYTES])
            del self._pending[:FRAME_BYTES]
            if self._queue.full():
                self._queue.get_nowait()
                log.warning("mic source overflowed; dropped oldest frame")
            self._queue.put_nowait(frame)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(None)

    async def frames(self) -> AsyncIterator[bytes]:
        while (frame := await self._queue.get()) is not None:
            yield frame


class FileSource:
    """A recorded call (WAV, 16 kHz mono 16-bit), paced in real time by default."""

    kind: Literal["mic", "replay"] = "replay"

    def __init__(self, path: Path, realtime: bool = True) -> None:
        self.path = Path(path)
        self.realtime = realtime
        self._closed = False
        with wave.open(str(self.path), "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                raise ValueError(
                    f"{self.path.name}: need 16 kHz mono 16-bit WAV, got "
                    f"{wav.getframerate()} Hz, {wav.getnchannels()} ch, {wav.getsampwidth() * 8}-bit"
                )
            self.duration_s = wav.getnframes() / SAMPLE_RATE

    def close(self) -> None:
        self._closed = True

    async def frames(self) -> AsyncIterator[bytes]:
        start = time.monotonic()
        sent = 0
        with wave.open(str(self.path), "rb") as wav:
            while not self._closed:
                frame = wav.readframes(FRAME_SAMPLES)
                if not frame:
                    break
                if len(frame) < FRAME_BYTES:
                    frame += b"\x00" * (FRAME_BYTES - len(frame))
                yield frame
                sent += 1
                if self.realtime:
                    # Pace against the start time so delays don't accumulate.
                    delay = start + sent * FRAME_SECONDS - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(0)


def frame_dbfs(frame: bytes) -> float:
    """Loudness of one PCM frame in dBFS (0 = full scale, floor -100)."""
    samples = np.frombuffer(frame, dtype="<i2").astype(np.float64)
    if samples.size == 0:
        return -100.0
    rms = float(np.sqrt(np.mean(samples**2)))
    return max(-100.0, 20 * math.log10(max(rms, 1e-9) / 32768))
