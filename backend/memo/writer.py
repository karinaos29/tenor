"""Memo writer: collects the call from the bus and writes the decision memo after hang-up.

The memo itself is built from facts (memo/builder.py). Gemini only words the short
summary, hedged across models, and the result is used only if it passes two guards:
every number must come from the facts, and no buy / sell / safe / scam. Otherwise the
template summary stays. The memo is saved to SQLite; `call.ended` never waits for it.

Consumes: CallStarted, UtteranceFinal, SpeakersUpdated, OfferUpdated, ClaimChecked,
ResearchReady, TacticFlagged, SuggestionsUpdated, RiskUpdated, CallEnded.
Publishes: MemoReady (best effort; the browser polls GET /api/calls/{id}/memo).
"""

import asyncio
import logging
import re
import time

from memo.builder import CallRecord, build_memo, facts_text, sections, template_summary
from memo.store import MemoStore
from pipeline.bus import EventBus
from pipeline.events import (
    CallEnded,
    CallStarted,
    ClaimChecked,
    Memo,
    MemoReady,
    OfferUpdated,
    ResearchReady,
    RiskUpdated,
    SpeakersUpdated,
    SuggestionsUpdated,
    TacticFlagged,
    UtteranceFinal,
    utc_now,
)
from pipeline.latency import record
from pipeline.llm import HedgedLlm, LlmClient
from pipeline.research import number_guard

log = logging.getLogger("tenor.memo")

# No advice words, and no inflating a source (the register is a test register; Gemini
# called it "the official register" on a real run).
FORBIDDEN = re.compile(r"\b(buy|buying|sell|selling|safe|scam|scams|scammer|official)\b", re.I)

SUMMARY_SYSTEM = """You write the summary at the top of a decision memo for Eszter, 58, a retired teacher who
is not a finance expert, right after an unsolicited investment call. Write 3 or 4 short, calm sentences in
plain words. Use only the facts given; keep numbers exactly as written, in digits. Do not give advice, do not
tell her what to do, and never use the words buy, sell, safe or scam. Don't make sources sound more official
than they are."""


def summary_ok(text: str, facts: str) -> bool:
    return bool(text.strip()) and not FORBIDDEN.search(text) and number_guard(text, facts)


class MemoWriter:
    def __init__(
        self,
        bus: EventBus,
        store: MemoStore | None = None,
        llm: LlmClient | HedgedLlm | None = None,
        *,
        timeout_s: float = 20.0,
    ) -> None:
        self.bus = bus
        self.store = store
        self.llm = llm if llm is not None and llm.available else None
        self.timeout_s = timeout_s
        self.record = CallRecord()
        self.memo: Memo | None = None
        self._sub = bus.subscribe(
            CallStarted, UtteranceFinal, SpeakersUpdated, OfferUpdated, ClaimChecked, ResearchReady,
            TacticFlagged, SuggestionsUpdated, RiskUpdated, CallEnded,
        )  # fmt: skip

    async def run(self) -> Memo | None:
        r = self.record
        async for event in self._sub:
            if isinstance(event, CallStarted):
                r.call_id, r.source, r.replay_id, r.started_at = event.call_id, event.source, event.replay_id, event.ts
                await self._db(self.store.start if self.store else None, r.call_id, r.started_at.isoformat(), r.source, r.replay_id)
            elif isinstance(event, UtteranceFinal):
                r.utterances[event.utterance.id] = event.utterance
            elif isinstance(event, SpeakersUpdated):
                r.user_indices = set(event.user_indices)
            elif isinstance(event, OfferUpdated):
                r.offer = event.offer
            elif isinstance(event, ClaimChecked):
                r.claims[event.claim.id] = event.claim
            elif isinstance(event, ResearchReady):
                r.research[event.item.id] = event.item
            elif isinstance(event, TacticFlagged):
                r.flags.append(event.flag)
            elif isinstance(event, SuggestionsUpdated):
                for s in [*event.visible, *event.earlier]:
                    if s.kind == "say_this":
                        r.say_this[s.id] = s
            elif isinstance(event, RiskUpdated):
                r.risk = event
            elif isinstance(event, CallEnded):
                r.ended_at = event.ts
                break
        self._sub.close()
        return await self.write()

    async def write(self) -> Memo | None:
        r = self.record
        started = time.perf_counter()
        await self._db(self.store.set_status if self.store else None, r.call_id, "writing")
        try:
            secs = sections(r)
            summary, wording = template_summary(r), "template"
            if self.llm is not None:
                facts = facts_text(r, secs)
                prompt = f"Facts:\n{facts}\n\nTemplate summary (you may reword it): {summary}"
                kwargs = {"accept": lambda t: summary_ok(t, facts)} if isinstance(self.llm, HedgedLlm) else {}
                try:
                    text = await asyncio.wait_for(
                        self.llm.generate_text(system=SUMMARY_SYSTEM, prompt=prompt, stage="llm.memo", call_id=r.call_id, **kwargs),
                        self.timeout_s,
                    )
                except TimeoutError:
                    text = None
                if text is not None and summary_ok(text, facts):
                    summary, wording = text, "gemini"
            self.memo = build_memo(r, summary, wording, secs)
            await self._db(self.store.save_memo if self.store else None, self.memo)
        except Exception:  # noqa: BLE001 - a broken memo must not crash the server
            log.exception("memo failed for call %s", r.call_id)
            await self._db(self.store.set_status if self.store else None, r.call_id, "failed")
            return None
        ended = r.ended_at or utc_now()
        record("memo.write", (utc_now() - ended).total_seconds() * 1000, call_id=r.call_id, wording=wording,
               build_ms=round((time.perf_counter() - started) * 1000, 1))  # fmt: skip
        self.bus.publish(MemoReady(call_id=r.call_id))
        return self.memo

    @staticmethod
    async def _db(fn, *args) -> None:  # noqa: ANN001
        if fn is None:
            return
        try:
            await asyncio.to_thread(fn, *args)
        except Exception:  # noqa: BLE001 - storage problems are logged, not fatal
            log.exception("memo store failed")
