"""One call: wires an audio source into the pipeline and streams UI events out.

    source -> level meter (audio.level) -> transcriber -> labeler -> utterance.*
                                                  \\-> transcriber.status
    utterance.final -> extractor -> entity.* / claim.* -> offer tracker -> offer.*
    claim.* / offer.* -> claim checker (data + arithmetic) -> claim.checked
    entity.* (ticker, firm) -> research agent (prefetch, LLM rewords) -> research.ready
    utterance.* (caller sentences) -> pressure detector (classifier + rules) -> tactic.flagged
    claim.checked / research.ready / offer.* / tactic.flagged -> suggestion engine -> suggestions.updated, risk.updated

End of call is a chain, so nothing is cut off: transcript.closed -> labeler ->
utterances.closed -> extractor (waits for pending LLM calls) -> entities.closed ->
offer tracker, and checker + research drain -> checks.closed / research.closed ->
suggestion engine's final state -> call.ended -> memo writer (in the background: the memo is
saved to SQLite; the browser polls GET /api/calls/{id}/memo, so hanging up never waits on an LLM).

The session owns the bus and the task lifecycle; components only see the bus.
Live mic and replay run through exactly this code.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from audio.sources import FRAME_SECONDS, AudioSource, frame_bands, frame_dbfs
from pipeline.bus import EventBus, Subscription
from pipeline.events import (
    AudioLevel,
    CallEnded,
    CallStarted,
    ChecksClosed,
    ClaimChecked,
    EntitiesClosed,
    Event,
    OfferChanged,
    OfferClosed,
    OfferUpdated,
    ResearchClosed,
    ResearchReady,
    RiskUpdated,
    SpeakersSwap,
    SpeakersUpdated,
    SuggestionsUpdated,
    TacticFlagged,
    TacticsClosed,
    TranscriberStatus,
    TranscriptClosed,
    UtterancesClosed,
    UtteranceFinal,
    UtterancePartial,
)
from pipeline.checker import ClaimChecker
from pipeline.extractor import EntityExtractor
from pipeline.llm import HedgedLlm, LlmClient
from pipeline.offer import OfferTracker
from pipeline.research import ResearchAgent
from pipeline.speakers import SpeakerLabeler
from pipeline.suggestions import SuggestionEngine
from pipeline.tactics import PressureDetector
from memo.store import MemoStore
from memo.writer import MemoWriter
from detector.classifier import TacticClassifier
from providers.catalog import Catalog, default_catalog
from providers.market import FixtureProvider, MarketDataProvider, RoutedMarketData
from providers.register import FixtureRegister
from pipeline.transcriber import AudioItem, Transcriber, TranscriberContext

log = logging.getLogger("tenor.session")

# Events the browser sees. Everything else stays on the bus.
UI_EVENTS: tuple[type[Event], ...] = (
    CallStarted,
    TranscriberStatus,
    SpeakersUpdated,
    UtterancePartial,
    UtteranceFinal,
    OfferUpdated,
    OfferChanged,
    ClaimChecked,
    ResearchReady,
    SuggestionsUpdated,
    RiskUpdated,
    TacticFlagged,
    CallEnded,
)

AUDIO_BUFFER_FRAMES = 63  # ~5 s of audio, enough to ride out a speech-to-text reconnect
TRANSCRIBER_FINISH_TIMEOUT = 10.0  # real time; fast replays get FAST_FINISH_TIMEOUT
FAST_FINISH_TIMEOUT = 30.0
LABELER_FINISH_TIMEOUT = 2.0
EXTRACTOR_FINISH_TIMEOUT = 10.0  # covers pending LLM calls (8 s budget each, run in parallel)
TRACKER_FINISH_TIMEOUT = 1.0
VERIFY_FINISH_TIMEOUT = 10.0  # checker + research drain (provider timeouts 3 s, wording 6 s)
SUGGESTIONS_FINISH_TIMEOUT = 2.0

Send = Callable[[Event], Awaitable[None]]


class CallSession:
    def __init__(
        self,
        source: AudioSource,
        transcriber: Transcriber,
        send: Send,
        *,
        replay_id: str | None = None,
        catalog: Catalog | None = None,
        llm: LlmClient | HedgedLlm | None = None,
        market: MarketDataProvider | None = None,
        register: FixtureRegister | None = None,
        wording_timeout: float = 6.0,
        classifier: TacticClassifier | None = None,
        store: MemoStore | None = None,
        memo_llm: LlmClient | HedgedLlm | None = None,
        memo_timeout: float = 20.0,
        forward: tuple[type[Event], ...] = UI_EVENTS,
    ) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.source = source
        self.transcriber = transcriber
        self.send = send
        self.replay_id = replay_id
        self.catalog = catalog or default_catalog()
        self.llm = llm  # None = rules-only extraction, template wording
        # Default: test data only (no network). The gateway and replay CLI pass Finnhub in.
        self.market = market or RoutedMarketData(FixtureProvider(self.catalog), None)
        self.register = register or FixtureRegister(self.catalog)
        self.wording_timeout = wording_timeout
        self.classifier = classifier  # None = tactic rules only
        self.store = store
        self.memo_llm = memo_llm
        self.memo_timeout = memo_timeout
        self.memo_task: asyncio.Task | None = None  # finishes after the call; never awaited by run()
        self.forward = forward
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
        forwarder = asyncio.create_task(self._forward(self.bus.subscribe(*self.forward)))
        kind = self.source.kind
        # Components subscribe in their constructors, before any event is published.
        labeler = asyncio.create_task(SpeakerLabeler(self.bus, self.id, kind).run())
        extractor = asyncio.create_task(EntityExtractor(self.bus, self.catalog, self.llm, call_id=self.id, source=kind).run())
        tracker = asyncio.create_task(OfferTracker(self.bus, call_id=self.id, source=kind).run())
        ctx = TranscriberContext(call_id=self.id, source=self.source.kind, realtime=self.source.realtime)

        def clock(t_call: float) -> float | None:
            """Monotonic time at which call-time `t_call` was spoken (real-time sources only)."""
            return ctx.wall_start + t_call if ctx.wall_start is not None and ctx.realtime else None

        checker = asyncio.create_task(ClaimChecker(self.bus, self.market, call_id=self.id, source=kind, clock=clock).run())
        research = asyncio.create_task(
            ResearchAgent(
                self.bus, self.market, self.register, self.catalog, self.llm,
                call_id=self.id, source=kind, wording_timeout=self.wording_timeout,
            ).run()
        )  # fmt: skip
        tactics = asyncio.create_task(PressureDetector(self.bus, self.classifier, call_id=self.id, source=kind).run())
        # The memo writer collects the whole call and writes after call.ended, in the background.
        self.memo_task = asyncio.create_task(MemoWriter(self.bus, self.store, self.memo_llm, timeout_s=self.memo_timeout).run())
        suggestions = asyncio.create_task(
            SuggestionEngine(self.bus, call_id=self.id, wait_for=("checks", "research", "tactics")).run()
        )
        audio: asyncio.Queue[AudioItem] = asyncio.Queue(maxsize=AUDIO_BUFFER_FRAMES + 1)

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
            await self._finish(labeler, LABELER_FINISH_TIMEOUT, on_timeout=UtterancesClosed())
            await self._finish(extractor, EXTRACTOR_FINISH_TIMEOUT, on_timeout=EntitiesClosed())
            await self._finish(tracker, TRACKER_FINISH_TIMEOUT, on_timeout=OfferClosed())
            await self._finish(checker, VERIFY_FINISH_TIMEOUT, on_timeout=ChecksClosed())
            await self._finish(research, VERIFY_FINISH_TIMEOUT, on_timeout=ResearchClosed())
            await self._finish(tactics, VERIFY_FINISH_TIMEOUT, on_timeout=TacticsClosed())
            await self._finish(suggestions, SUGGESTIONS_FINISH_TIMEOUT)
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
            bass_db, voice_db = frame_bands(frame)
            self.bus.publish(AudioLevel(t=t, dbfs=frame_dbfs(frame), bass_db=bass_db, voice_db=voice_db))
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
