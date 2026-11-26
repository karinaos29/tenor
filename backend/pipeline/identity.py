"""Identity watcher: notices when a caller who is pitching doesn't say which firm they're from.

Two gaps, both plain facts about the call (no model involved):
- "missing": the call is a pitch (a tactic, a claim, or an offer term was heard), at least
  `missing_after_s` seconds have passed, and the caller hasn't named a firm. Resolved if a
  firm is named later.
- "evaded": someone asked which firm the caller is from, and the caller's next
  `answer_turns` turns (or `answer_within_s` seconds) passed without a firm. Never resolved:
  the dodge happened even if a name comes later.

The question is matched in any speaker's words, because speakerphone diarization can
label Eszter's question as the caller's (a caller doesn't ask where they're calling from).

Each utterance is judged one turn late, once the firm entity for that turn (rules, or the
LLM ~1 s later) has reached the offer, so a reason never flickers on and off.

Consumes: UtteranceFinal, OfferUpdated, TacticFlagged, ClaimExtracted, OfferClosed, TacticsClosed.
Publishes: IdentityGap, IdentityResolved, IdentityClosed.
"""

import re
import time
from dataclasses import dataclass

from pipeline.bus import EventBus
from pipeline.events import (
    ClaimExtracted,
    IdentityClosed,
    IdentityGap,
    IdentityResolved,
    OfferClosed,
    OfferUpdated,
    TacticFlagged,
    TacticsClosed,
    Utterance,
    UtteranceFinal,
)
from pipeline.latency import record

MISSING_AFTER_S = 40.0
ANSWER_TURNS = 2
ANSWER_WITHIN_S = 20.0

_ORG = r"(?:company|firm|bank|business|organi[sz]ation)"
FIRM_QUESTION = re.compile(
    rf"\b(?:which|what)\s+{_ORG}\s+(?:are|were)\s+you\b"
    rf"|\b(?:which|what)\s+{_ORG}\s+(?:is\s+(?:this|that)|do\s+you\s+(?:work\s+(?:for|at)|represent))\b"
    rf"|\b(?:what'?s|what\s+is)\s+(?:the\s+name\s+of\s+)?your\s+{_ORG}\b"
    rf"|\b(?:what'?s|what\s+is)\s+the\s+name\s+of\s+the\s+{_ORG}\b"
    rf"|\byou(?:'re|\s+are)\s+(?:from|with|calling\s+from)\s+(?:which|what)\s+{_ORG}\b"
    r"|\bwho\s+(?:are\s+you|do\s+you\s+work)\s+(?:with|for)\b"
    r"|\bwhere\s+are\s+you\s+calling\s+from\b"
    r"|\bwho\s+are\s+you\s+calling\s+(?:from|for|on\s+behalf\s+of)\b"
    r"|\bwho\s+do\s+you\s+(?:represent|work\s+for)\b",
    re.IGNORECASE,
)
PITCH_FIELDS = ("instrument", "price", "quantity", "total", "fees", "deadline", "payment")


@dataclass
class _Question:
    text: str
    t: float
    caller_turns: int = 0


class IdentityWatcher:
    def __init__(
        self,
        bus: EventBus,
        *,
        call_id: str = "",
        source: str = "",
        missing_after_s: float = MISSING_AFTER_S,
        answer_turns: int = ANSWER_TURNS,
        answer_within_s: float = ANSWER_WITHIN_S,
    ) -> None:
        self.bus = bus
        self.call_id = call_id
        self.source = source
        self.missing_after_s = missing_after_s
        self.answer_turns = answer_turns
        self.answer_within_s = answer_within_s
        self._sub = bus.subscribe(UtteranceFinal, OfferUpdated, TacticFlagged, ClaimExtracted, OfferClosed, TacticsClosed)
        self._firm: str | None = None
        self._pitch = False
        self._gap: str | None = None  # None, "missing" or "evaded"
        self._question: _Question | None = None
        self._pending: Utterance | None = None  # the last utterance, judged when the next one arrives
        self._clock = 0.0

    async def run(self) -> None:
        closed: set[str] = set()
        async for event in self._sub:
            if isinstance(event, UtteranceFinal):
                self._judge_pending()
                self._pending = event.utterance
            elif isinstance(event, OfferUpdated):
                self._on_offer(event)
            elif isinstance(event, TacticFlagged | ClaimExtracted):
                self._pitch = True
            elif isinstance(event, OfferClosed):
                closed.add("offer")
            elif isinstance(event, TacticsClosed):
                closed.add("tactics")
            if {"offer", "tactics"} <= closed:
                break
        self._judge_pending()
        self._final()
        self.bus.publish(IdentityClosed())
        self._sub.close()

    def _on_offer(self, event: OfferUpdated) -> None:
        offer = event.offer
        self._pitch |= any(getattr(offer, f) is not None for f in PITCH_FIELDS)
        if offer.firm is not None and self._firm is None:
            self._firm = offer.firm.display
            self._question = None  # the question was answered
            if self._gap == "missing":
                self._gap = None
                self.bus.publish(IdentityResolved(firm=self._firm))

    def _judge_pending(self) -> None:
        """Judge the previous utterance, now that its firm entity (if any) has arrived."""
        u, self._pending = self._pending, None
        if u is None:
            return
        started = time.perf_counter()
        self._clock = max(self._clock, u.t_end)
        if self._firm is None:
            q = self._question
            if q is not None and u.speaker == "caller":
                q.caller_turns += 1
            if q is None and FIRM_QUESTION.search(u.text):
                self._question = _Question(text=u.text, t=u.t_end)
            elif q is not None and (q.caller_turns >= self.answer_turns or self._clock - q.t >= self.answer_within_s):
                self._evaded(q)
            if self._gap is None and self._pitch and self._clock >= self.missing_after_s:
                self._gap = "missing"
                self.bus.publish(IdentityGap(kind="missing", t=self._clock))
        record("identity", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source)

    def _final(self) -> None:
        """End of call: a question the caller talked past but never answered still counts."""
        q = self._question
        if self._firm is None and q is not None and q.caller_turns >= 1:
            self._evaded(q)

    def _evaded(self, q: _Question) -> None:
        self._question = None
        if self._gap != "evaded":
            self._gap = "evaded"
            self.bus.publish(IdentityGap(kind="evaded", t=self._clock, question=q.text))
