"""One call: wires an audio source into the pipeline and streams UI events out.

    source -> level meter (audio.level) -> transcriber -> labeler -> utterance.*
                                                  \\-> transcriber.status

The session owns the bus and the task lifecycle; components only see the bus.
Live mic and replay run through exactly this code.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from audio.sources import FRAME_SECONDS, AudioSource, frame_dbfs
from pipeline.bus import EventBus, Subscription
from pipeline.events import (
    AudioLevel,
    CallEnded,
    CallStarted,
    Event,
    SpeakersSwap,
    SpeakersUpdated,
    TranscriberStatus,
    TranscriptClosed,
    UtteranceFinal,
    UtterancePartial,
)
from pipeline.speakers import SpeakerLabeler
from pipeline.transcriber import AudioItem, Transcriber, TranscriberContext

log = logging.getLogger("tenor.session")

# Events the browser sees. Everything else stays on the bus.
UI_EVENTS: tuple[type[Event], ...] = (
    CallStarted,
    TranscriberStatus,
    SpeakersUpdated,
    UtterancePartial,
    UtteranceFinal,
    CallEnded,
)

AUDIO_BUFFER_FRAMES = 63  # ~5 s of audio, enough to ride out a speech-to-text reconnect
TRANSCRIBER_FINISH_TIMEOUT = 10.0  # real time; fast replays get FAST_FINISH_TIMEOUT
FAST_FINISH_TIMEOUT = 30.0
LABELER_FINISH_TIMEOUT = 2.0

Send = Callable[[Event], Awaitable[None]]


class CallSession:
    def __init__(
        self,
        source: AudioSource,
        transcriber: Transcriber,
        send: Send,
        *,
        replay_id: str | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.source = source
        self.transcriber = transcriber
        self.send = send
        self.replay_id = replay_id
        self.bus = EventBus()
        self._stopped_by_user = False
        self._client_gone = False

    def stop(self) -> None:
        """End the call (user hung up, or the browser went away)."""
        self._stopped_by_user = True
        self.source.close()

    def swap_speakers(self) -> None:
        self.bus.publish(SpeakersSwap())

    async def run(self) -> None:
        forwarder = asyncio.create_task(self._forward(self.bus.subscribe(*UI_EVENTS)))
        labeler = asyncio.create_task(SpeakerLabeler(self.bus, self.id, self.source.kind).run())
        audio: asyncio.Queue[AudioItem] = asyncio.Queue(maxsize=AUDIO_BUFFER_FRAMES + 1)
        ctx = TranscriberContext(call_id=self.id, source=self.source.kind, realtime=self.source.realtime)

        self.bus.publish(CallStarted(call_id=self.id, source=self.source.kind, replay_id=self.replay_id))
        transcriber = asyncio.create_task(self.transcriber.run(audio, self.bus, ctx))
        reason: str = "replay_finished" if self.source.kind == "replay" else "user"
        detail = ""
        try:
            await self._pump(audio, ctx)
        except Exception as e:  # a broken source must still end the call cleanly
            log.exception("audio source failed")
            reason, detail = "error", type(e).__name__
        finally:
            self._put(audio, None)
            finish = TRANSCRIBER_FINISH_TIMEOUT if self.source.realtime else FAST_FINISH_TIMEOUT
            await self._finish(transcriber, finish, on_timeout=TranscriptClosed())
            await self._finish(labeler, LABELER_FINISH_TIMEOUT)
            if self._stopped_by_user and reason != "error":
                reason = "user"
            self.bus.publish(CallEnded(reason=reason, detail=detail))  # type: ignore[arg-type]
            await self._finish(forwarder, 2.0)
            self.bus.close()

    async def _pump(self, audio: "asyncio.Queue[AudioItem]", ctx: TranscriberContext) -> None:
        index = 0
        async for frame in self.source.frames():
            if index == 0:
                ctx.wall_start = time.monotonic()
            t = index * FRAME_SECONDS
            # Level first, so the labeler always has loudness for the words that follow.
            self.bus.publish(AudioLevel(t=t, dbfs=frame_dbfs(frame)))
            if self.source.realtime:
                self._put(audio, (t, frame))  # live audio can't wait: drop the oldest if behind
            else:
                await audio.put((t, frame))  # a file can wait for the transcriber
            index += 1

    @staticmethod
    def _put(audio: "asyncio.Queue[AudioItem]", item: AudioItem) -> None:
        if audio.full():
            audio.get_nowait()  # drop the oldest audio rather than block the source
        audio.put_nowait(item)

    async def _finish(self, task: asyncio.Task, timeout: float, on_timeout: Event | None = None) -> None:
        try:
            await asyncio.wait_for(task, timeout)
        except TimeoutError:
            log.warning("session %s: task did not finish in %.0f s", self.id, timeout)
            if on_timeout is not None:
                self.bus.publish(on_timeout)
        except Exception:
            log.exception("session %s: task failed", self.id)

    async def _forward(self, sub: Subscription) -> None:
        async for event in sub:
            if not self._client_gone:
                try:
                    await self.send(event)
                except Exception:
                    log.info("session %s: client went away", self.id)
                    self._client_gone = True
                    self.stop()
            if isinstance(event, CallEnded):
                break
        sub.close()
