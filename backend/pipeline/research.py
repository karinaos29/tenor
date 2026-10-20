"""Research agent, slow lane with prefetch: data first, the LLM only rewords.

On the first mention of a ticker or firm it publishes a "prefetching" item at once,
fetches facts from the providers (no LLM involved), and publishes a "ready" item with a
template summary built from those facts. Then, if Gemini is available, it asks for a
plain-words rewording under a number guard: every number in the new text must appear in
the facts, otherwise the template stays. The verdict-free facts are always the source.

Consumes: EntityDetected, EntitiesClosed. Publishes: ResearchReady, ResearchClosed.
"""

import asyncio
import logging
import re
import time

from pipeline.bus import EventBus
from pipeline.events import EntitiesClosed, EntityDetected, Fact, ResearchClosed, ResearchItem, ResearchReady, utc_now
from pipeline.latency import record
from pipeline.llm import HedgedLlm, LlmClient
from pipeline.numbers import normalize
from providers.catalog import Catalog
from providers.market import WINDOW_LABEL, MarketDataProvider
from providers.register import FixtureRegister

log = logging.getLogger("tenor.research")

WORDING_SYSTEM = """You rewrite research facts for Eszter, 58, a retired teacher who is not a finance
expert and is listening to a phone call right now. Write one or two short, calm sentences in plain words.
Use only the facts given. Keep every number exactly as written, in digits (e.g. 12.5%, $0.38).
Do not add numbers, advice or opinions. Don't make sources sound more official than they are
(say "the register", not "the official register"). Never say buy, sell, safe or scam."""

_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")


def numbers_in(text: str) -> set[str]:
    # Normalize first, so numbers written as words ("forty percent") can't slip past the guard.
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(normalize(text).text)}


def number_guard(text: str, allowed_text: str, required_text: str = "") -> bool:
    """True if every number in `text` appears in the facts, and every percentage in
    `required_text` (the template) is still there, so the key figure can't be dropped."""
    found = numbers_in(text)
    required = {m.rstrip(".") for m in _PCT.findall(required_text)}
    return found <= numbers_in(allowed_text) and required <= found


def pct_words(x: float) -> str:
    return f"up {abs(x):g}%" if x >= 0 else f"down {abs(x):g}%"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class ResearchAgent:
    def __init__(
        self,
        bus: EventBus,
        market: MarketDataProvider,
        register: FixtureRegister,
        catalog: Catalog,
        llm: LlmClient | HedgedLlm | None = None,
        *,
        call_id: str = "",
        source: str = "",
        wording_timeout: float = 6.0,
        drain_timeout: float = 8.0,
    ) -> None:
        self.bus = bus
        self.market = market
        self.register = register
        self.catalog = catalog
        self.llm = llm if llm is not None and llm.available else None
        self.call_id = call_id
        self.source = source
        self.wording_timeout = wording_timeout
        self.drain_timeout = drain_timeout
        self._sub = bus.subscribe(EntityDetected, EntitiesClosed)
        self._seen: set[tuple[str, str]] = set()
        self._pending: set[asyncio.Task] = set()

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, EntityDetected) and event.entity.kind in ("ticker", "firm"):
                e = event.entity
                if e.kind == "ticker" and e.confidence == "unsure":
                    continue  # don't research a symbol we may have misheard
                key = (e.kind, e.value.upper())
                if key not in self._seen:
                    self._seen.add(key)
                    task = asyncio.create_task(self._research(e.kind, e.value))
                    self._pending.add(task)
                    task.add_done_callback(self._pending.discard)
            elif isinstance(event, EntitiesClosed):
                break
        if self._pending:
            _, late = await asyncio.wait(self._pending, timeout=self.drain_timeout)
            for task in late:
                task.cancel()
        self.bus.publish(ResearchClosed())
        self._sub.close()

    async def _research(self, topic: str, subject: str) -> None:
        item_id = f"r-{topic}-{slug(subject)}"
        title = f"How {subject} has really done" if topic == "ticker" else f"Who is {subject}?"
        base = ResearchItem(id=item_id, topic=topic, subject=subject, title=title, status="prefetching")  # type: ignore[arg-type]
        self.bus.publish(ResearchReady(item=base))
        started = time.perf_counter()
        try:
            if topic == "ticker":
                facts, summary, source, ok = await self._ticker(subject)
                finding = None
            else:
                facts, summary, source, ok, finding = await self._firm(subject)
        except Exception:  # noqa: BLE001
            log.exception("research failed for %s", subject)
            facts, summary, source, ok, finding = [], f"Couldn't check {subject} right now.", "", False, None
        record("research.prefetch", (time.perf_counter() - started) * 1000, call_id=self.call_id, topic=topic)
        ready = base.model_copy(
            update={
                "status": "ready" if ok else "failed",
                "facts": facts,
                "summary": summary,
                "source": source,
                "checked_at": utc_now(),
                "finding": finding,
            }
        )
        self.bus.publish(ResearchReady(item=ready))
        if ok and self.llm is not None:
            await self._reword(ready)

    async def _reword(self, item: ResearchItem) -> None:
        facts_text = "\n".join(f"- {f.label}: {f.value}" for f in item.facts)
        allowed = facts_text + "\n" + item.summary
        prompt = f"Subject: {item.subject}\nFacts:\n{facts_text}\nCurrent wording: {item.summary}"
        started = time.perf_counter()
        try:
            text = await asyncio.wait_for(
                self.llm.generate_text(  # type: ignore[union-attr]
                    system=WORDING_SYSTEM,
                    prompt=prompt,
                    stage="llm.wording",
                    call_id=self.call_id,
                    **({"accept": lambda t: number_guard(t, allowed, item.summary)} if isinstance(self.llm, HedgedLlm) else {}),
                ),
                self.wording_timeout,
            )
        except TimeoutError:
            text = None
        ok = text is not None and number_guard(text, allowed, item.summary)
        record("research.wording", (time.perf_counter() - started) * 1000, call_id=self.call_id, ok=ok)
        if ok:
            self.bus.publish(ResearchReady(item=item.model_copy(update={"summary": text, "wording": "gemini"})))

    async def _ticker(self, symbol: str) -> tuple[list[Fact], str, str, bool]:
        quote, returns, profile, news = await asyncio.gather(
            self.market.quote(symbol), self.market.returns(symbol), self.market.profile(symbol), self.market.news(symbol, 90)
        )
        company = self.catalog.ticker(symbol)
        name = (profile.name if profile else None) or (company.name if company else symbol)
        facts: list[Fact] = []
        parts: list[str] = []
        if profile and profile.exchange:
            facts.append(Fact(label="Listed on", value=profile.exchange, source=profile.source))
        if quote:
            facts.append(Fact(label="Price now", value=f"${quote.price:,.2f}", source=quote.source))
            parts.append(f"{name} ({symbol}) trades at ${quote.price:,.2f}" + (f" on {profile.exchange}" if profile and profile.exchange else "") + ".")
        if returns:
            for window in ("13w", "ytd", "52w"):
                if window in returns.pct:
                    value = round(returns.pct[window], 1)
                    facts.append(Fact(label=WINDOW_LABEL[window].capitalize(), value=f"{value:+g}%", source=returns.source))
            spans = [f"{WINDOW_LABEL[w]} {pct_words(round(returns.pct[w], 1))}" for w in ("13w", "52w") if w in returns.pct]
            if spans:
                parts.append("Price change: " + "; ".join(spans) + ".")
        if news is not None:
            facts.append(Fact(label="News, last 90 days", value=f"{len(news)} articles", source="Company news"))
            parts.append("No news in the last 90 days." if not news else f"{len(news)} news articles in the last 90 days.")
        if not (quote or returns):
            return facts, f"Couldn't find market data for {symbol}.", "", False
        source = (returns or quote).source  # type: ignore[union-attr]
        return facts, " ".join(parts), source, True

    async def _firm(self, firm: str) -> tuple[list[Fact], str, str, bool, str | None]:
        result = await self.register.lookup(firm)
        fact = Fact(label="Register", value=result.detail, source=result.source)
        if result.status == "registered":
            return [fact], f"{firm} is in the register. {result.detail}.", result.source, True, "registered"
        if result.status == "not_found":
            summary = f"{firm} is not in the register. Investment firms are normally registered."
            return [fact], summary, result.source, True, "not_registered"
        return [fact], f"Couldn't check {firm}: there's no register connection for it in this prototype.", "", False, None
