"""Pressure detector: flags pressure tactics in the caller's sentences.

Each finished caller sentence (from utterance.progress or utterance.final, as in the
extractor) is scored by the classifier (embeddings + logistic regression, in a worker
thread) and by the high-precision rules. A tactic is flagged when either fires.
Severity is "strong" when a rule matched or the classifier is very confident (>= 0.9);
a classifier-only flag below that is "mild": shown, but it barely moves the risk.
(The first evaluation showed classifier-only flags on honest small talk, so they need
corroboration before they count.)

Consumes: UtteranceProgress, UtteranceFinal, UtterancesClosed.
Publishes: TacticFlagged, TacticsClosed.
"""

import asyncio
import re
import time

from detector.classifier import TacticClassifier
from detector.rules import rule_tactics
from detector.taxonomy import BY_ID
from pipeline.bus import EventBus
from pipeline.events import (
    SpeakersUpdated,
    TacticFlag,
    TacticFlagged,
    TacticsClosed,
    Utterance,
    UtteranceFinal,
    UtteranceProgress,
    UtterancesClosed,
)
from pipeline.latency import record

STRONG_P = 0.9
_SENTENCE_END = re.compile(r"[.?!](?=\s|$)")
_SPLIT = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9\"“])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text) if s.strip()]


class PressureDetector:
    def __init__(
        self,
        bus: EventBus,
        classifier: TacticClassifier | None = None,
        *,
        call_id: str = "",
        source: str = "",
    ) -> None:
        self.bus = bus
        self.classifier = classifier
        self.call_id = call_id
        self.source = source
        self._sub = bus.subscribe(UtteranceProgress, UtteranceFinal, UtterancesClosed, SpeakersUpdated)
        self._recent: list[Utterance] = []
        self._reprocessed: set[str] = set()
        self._done: dict[str, int] = {}
        self._count = 0

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, (UtteranceProgress, UtteranceFinal)):
                await self._chunk(event.utterance, final=isinstance(event, UtteranceFinal))
                if isinstance(event, UtteranceFinal):
                    self._recent = (self._recent + [event.utterance])[-20:]
            elif isinstance(event, SpeakersUpdated):
                # A line first labeled "You" turned out to be the caller's: score it now.
                for u in self._recent:
                    if u.speaker == "user" and u.speaker_index not in event.user_indices and u.id not in self._reprocessed:
                        self._reprocessed.add(u.id)
                        for sentence in sentences(u.text):
                            await self._score(u, sentence)
            elif isinstance(event, UtterancesClosed):
                break
        self.bus.publish(TacticsClosed())
        self._sub.close()

    async def _chunk(self, u: Utterance, final: bool) -> None:
        done = self._done.get(u.id, 0)
        end = len(u.text) if final else max((m.end() for m in _SENTENCE_END.finditer(u.text, done)), default=done)
        chunk = u.text[done:end].strip()
        self._done[u.id] = end
        if final:
            self._done.pop(u.id, None)
        if chunk and u.speaker == "caller":
            for sentence in sentences(chunk):
                await self._score(u, sentence)

    async def _score(self, u: Utterance, sentence: str) -> None:
        started = time.perf_counter()
        probs: dict[str, float] = {}
        if self.classifier is not None:
            probs = (await asyncio.to_thread(self.classifier.predict_proba, [sentence]))[0]
        rules = rule_tactics(sentence)
        flagged: set[str] = set()
        for tactic in BY_ID:
            p = probs.get(tactic, 0.0)
            by_classifier = self.classifier is not None and p >= self.classifier.thresholds[tactic]
            by_rule = tactic in rules
            if not (by_classifier or by_rule):
                continue
            strong = by_rule or p >= STRONG_P
            self._count += 1
            self.bus.publish(
                TacticFlagged(
                    flag=TacticFlag(
                        id=f"t{self._count}",
                        tactic=tactic,  # type: ignore[arg-type]
                        label=BY_ID[tactic].label,
                        quote=sentence,
                        severity="strong" if strong else "mild",
                        utterance_id=u.id,
                        score=round(p if by_classifier else 1.0, 3),
                        source="both" if by_classifier and by_rule else ("classifier" if by_classifier else "rule"),
                    )
                )
            )
            flagged.add(tactic)
        record("detector", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source)
