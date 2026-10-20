"""Entity extractor: offer terms, names and claims from each final utterance.

Stage 1, rules (sync, ~1 ms): prices, percents, quantities, deadlines, payment,
fees, person and firm names, tickers. Most entities never need an LLM.
Stage 2, Gemini (async, caller lines only, and only for fuzzy cases: company
events like "signed a deal", or names in the first lines that rules missed).
Anything the LLM returns must quote words that were actually said, or it's dropped.

Consumes: UtteranceFinal, UtterancesClosed.
Publishes: EntityDetected, ClaimExtracted, EntitiesClosed.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from pipeline.bus import EventBus
from pipeline.events import (
    Claim,
    ClaimExtracted,
    Confidence,
    EntitiesClosed,
    Entity,
    EntityDetected,
    EntityKind,
    Utterance,
    UtterancesClosed,
    UtteranceFinal,
)
from pipeline.latency import record
from pipeline.llm import LlmClient
from pipeline.numbers import Normalized, normalize
from providers.catalog import Catalog

log = logging.getLogger("tenor.extractor")

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"

_SENTENCE = re.compile(r"(?<=[.?!])\s+(?=[A-Z])")
_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_DOLLARS = re.compile(rf"\$\s?({_NUMBER})")
_CENTS = re.compile(r"\b(\d+(?:\.\d+)?)\s?(?:cents?\b|¢)", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent\b|per cent\b)", re.I)
_QUANTITY = re.compile(rf"\b({_NUMBER})\s+(shares|units)\b", re.I)
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?([ap])\.?\s?m\b\.?", re.I)
_DAYWORD = re.compile(rf"\b(today|tonight|tomorrow|this afternoon|this evening|end of (?:the )?(?:day|week)|{DAYS})\b", re.I)
_DATE = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)
_DEADLINE_CUE = re.compile(r"\b(until|by|before|expires?|deadline(?: is)?|closes?|locked|only|ends?)\s*$", re.I)
_PAYMENTS = [
    (re.compile(r"\bbank transfer\b", re.I), "Bank transfer"),
    (re.compile(r"\bwire(?: transfer)?\b", re.I), "Wire transfer"),
    (re.compile(r"\bgift cards?\b", re.I), "Gift cards"),
    (re.compile(r"\b(?:bitcoin|crypto(?:currency)?)\b", re.I), "Crypto"),
    (re.compile(r"\b(?:credit|debit) card\b", re.I), "Card"),
]
_FEE_CUE = re.compile(r"\b(fees?|commission|charges?)\b", re.I)
_YEARLY = re.compile(r"\b(?:a|per) year\b|\bannual(?:ly)?\b", re.I)
_PERSON = re.compile(r"\b(?:[Mm]y name is|[Tt]his is|I'm|I am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
_NOT_A_NAME = {"Just", "Calling", "Sorry", "Speaking", "Fine", "Great", "Here", "Not", "Afraid", "Happy", "Glad", "Sure", "Only"}
_CALLING_FROM = re.compile(r"\bcalling from\s+([A-Z][\w'-]*(?:\s+(?:and|&|of)?\s*[A-Z][\w'-]*){0,4})")
_SPELLED = re.compile(r"\b([A-Z](?:[ .-][A-Z]){1,4})\b")
_UPPER = re.compile(r"\b([A-Z]{2,5}(?:\.[A-Z])?)\b")
_TICKER_CUE = re.compile(r"\b(?:ticker|symbol)(?:\s+is)?[:,]?\s+([A-Za-z](?:[ .-]?[A-Za-z]){0,4})\b", re.I)

_UP = re.compile(r"\b(up|rose|risen|gained|grew|increased|jumped|soared|climbed)\b", re.I)
_DOWN = re.compile(r"\b(down|fell|dropped|lost|declined|decreased)\b", re.I)
_PERIOD = re.compile(rf"\b((?:this|last|past) (?:quarter|year|month|week)|today|since (?:{MONTHS}))\b", re.I)
_RETURN_WORD = re.compile(r"\b(returns?|yield|profit)\b", re.I)
_GUARANTEE = re.compile(r"\b(guarantee[ds]?|sure thing|can'?t lose|cannot lose|risk[- ]free|no risk)\b", re.I)
_NEGATED_GUARANTEE = re.compile(r"\b(?:don'?t|do not|doesn'?t|does not|not|never|no|can'?t|cannot)\s+(?:\w+\s+)?guarantee", re.I)
_MULTIPLE = {"double": 100.0, "triple": 200.0, "quadruple": 300.0}
_MULTIPLE_RE = re.compile(r"\b(double|triple|quadruple)\b", re.I)
_BY_WHEN = re.compile(rf"\bby (christmas|the end of (?:the )?year|next (?:year|month|week)|(?:{MONTHS}))\b", re.I)
_EXPENSE_RATIO = re.compile(r"\b(expense ratio|ongoing charge|management fee)\b", re.I)
_EVENT_CUE = re.compile(r"\b(signed|deal|partnership|contract|merger|acquisition|acquired|approved|approval|launch(?:ed|ing)?|patent)\b", re.I)


# --- Stage 1: rules -------------------------------------------------------------------


@dataclass
class RuleEntity:
    kind: EntityKind
    value: str
    text: str
    number: float | None = None
    unit: str | None = None
    detail: str | None = None
    confidence: Confidence = "heard"


@dataclass
class RuleClaim:
    text: str
    metric: Literal["price_change", "return", "guarantee", "event", "fee", "other"]
    claimed_value: float | None = None
    unit: str | None = None
    period: str | None = None


@dataclass
class RuleResult:
    entities: list[RuleEntity] = field(default_factory=list)
    claims: list[RuleClaim] = field(default_factory=list)


def money(n: float) -> str:
    return f"${n:,.2f}" if n < 1 or n != int(n) else f"${n:,.0f}"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _percent_value(s: str) -> float:
    """Deepgram's smart_format sometimes drops the decimal point ("a quarter percent" -> "025%").
    Nobody says a number with a leading zero, so "025" means 0.25."""
    if len(s) > 1 and s.startswith("0") and "." not in s:
        return float(f"0.{s[1:]}")
    return float(s)


def _clock(hour: int, minute: int, ampm: str) -> str:
    return f"{hour}:{minute:02d} {'PM' if ampm.lower() == 'p' else 'AM'}"


def _sentences(norm: Normalized) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE.finditer(norm.text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(norm.text)))
    return spans


class _Ctx:
    """Rule helpers over one utterance: normalized text + original text."""

    def __init__(self, text: str) -> None:
        self.original = text
        self.norm = normalize(text)
        self.n = self.norm.text

    def said(self, start: int, end: int) -> str:
        a, b = self.norm.original_span(start, end)
        return self.original[a:b]

    def sentence_of(self, pos: int) -> tuple[int, int]:
        for a, b in _sentences(self.norm):
            if a <= pos <= b:
                return a, b
        return 0, len(self.n)


def _prices(c: _Ctx, out: RuleResult) -> None:
    hits = [(m, _num(m.group(1))) for m in _DOLLARS.finditer(c.n)]
    hits += [(m, _num(m.group(1)) / 100) for m in _CENTS.finditer(c.n)]
    for m, value in hits:
        a, b = c.sentence_of(m.start())
        sentence = c.n[a:b]
        followed_by_shares = re.match(r"\s*(shares|units)\b", c.n[m.end() :], re.I)
        # A price per share needs share context in the same sentence ("the shares are 42 cents each").
        if not re.search(r"\bshares?\b", sentence, re.I) or followed_by_shares:
            continue
        out.entities.append(RuleEntity("price", f"{money(value)} a share", c.said(m.start(), m.end()), value, "USD"))


def _percents(c: _Ctx, out: RuleResult) -> None:
    for m in _PERCENT.finditer(c.n):
        value = _percent_value(m.group(1))
        out.entities.append(RuleEntity("percent", f"{value:g}%", c.said(m.start(), m.end()), value, "%"))


def _quantities(c: _Ctx, out: RuleResult) -> None:
    for m in _QUANTITY.finditer(c.n):
        value = _num(m.group(1))
        unit = m.group(2).lower()
        out.entities.append(RuleEntity("quantity", f"{value:,.0f} {unit}", c.said(m.start(), m.end()), value, unit))


def _cued(c: _Ctx, start: int) -> bool:
    """A deadline word must come right after a cue: "until 3 PM", "the deadline is April 15"."""
    return bool(_DEADLINE_CUE.search(c.n[max(0, start - 20) : start]))


def _deadlines(c: _Ctx, out: RuleResult) -> None:
    for m in _TIME.finditer(c.n):
        if not _cued(c, m.start()):
            continue
        clock = _clock(int(m.group(1)), int(m.group(2) or 0), m.group(3))
        end, day = m.end(), None
        if d := _DAYWORD.match(c.n[m.end() :].lstrip()):
            day = d.group(1)
            end = m.end() + (len(c.n[m.end() :]) - len(c.n[m.end() :].lstrip())) + d.end()
        value = f"{day.capitalize()}, {clock}" if day else clock
        out.entities.append(RuleEntity("deadline", value, c.said(m.start(), end)))
        return
    for m in _DATE.finditer(c.n):
        if _cued(c, m.start()):
            out.entities.append(RuleEntity("deadline", f"{m.group(1).capitalize()} {int(m.group(2))}", c.said(m.start(), m.end())))
            return
    for m in _DAYWORD.finditer(c.n):
        if _cued(c, m.start()):
            out.entities.append(RuleEntity("deadline", m.group(1).capitalize(), c.said(m.start(), m.end())))
            return


def _payments(c: _Ctx, out: RuleResult) -> None:
    for pattern, label in _PAYMENTS:
        if m := pattern.search(c.n):
            out.entities.append(RuleEntity("payment", label, c.said(m.start(), m.end())))
            return


def _fees(c: _Ctx, out: RuleResult) -> None:
    for a, b in _sentences(c.norm):
        sentence = c.n[a:b]
        if not _FEE_CUE.search(sentence) or re.search(r"expense ratio", sentence, re.I):
            continue
        if m := _PERCENT.search(sentence):
            value = _percent_value(m.group(1))
            yearly = " a year" if _YEARLY.search(sentence) else ""
            out.entities.append(RuleEntity("fee", f"{value:g}%{yearly}", c.said(a + m.start(), a + m.end()), value, "%"))
        elif m := _DOLLARS.search(sentence):
            value = _num(m.group(1))
            out.entities.append(RuleEntity("fee", money(value), c.said(a + m.start(), a + m.end()), value, "USD"))


def _names(c: _Ctx, catalog: Catalog, out: RuleResult) -> None:
    firm_spans: list[tuple[int, int]] = []
    lowered = c.n.lower()
    for firm in catalog.firms:
        for alias in sorted(firm.aliases, key=len, reverse=True):
            i = lowered.find(alias.lower())
            if i >= 0:
                out.entities.append(RuleEntity("firm", firm.name, c.said(i, i + len(alias)), confidence="matched"))
                firm_spans.append((i, i + len(alias)))
                break
        if firm_spans:
            break
    if not firm_spans and (m := _CALLING_FROM.search(c.n)):
        name = m.group(1).rstrip(".,")
        out.entities.append(RuleEntity("firm", name, c.said(m.start(1), m.start(1) + len(name))))
    # Rank candidates: "my name is" beats "this is", and a full name beats one word.
    # (Deepgram heard "is this Eszter?" as "This is Esther." before "This is Tom Becker".)
    candidates = []
    for m in _PERSON.finditer(c.n):
        name = m.group(1)
        if name.split()[0] in _NOT_A_NAME or any(a <= m.start(1) < b for a, b in firm_spans):
            continue
        intro = m.group(0).lower().startswith("my name is")
        candidates.append((intro, len(name.split()) > 1, -m.start(), m))
    if candidates:
        m = max(candidates, key=lambda x: x[:3])[3]
        out.entities.append(RuleEntity("person", m.group(1), c.said(m.start(1), m.end(1))))


def _tickers(c: _Ctx, catalog: Catalog, out: RuleResult) -> None:
    found: dict[str, RuleEntity] = {}

    def add(symbol: str, start: int, end: int, confidence: Confidence) -> None:
        company = catalog.ticker(symbol)
        if symbol not in found:
            found[symbol] = RuleEntity(
                "ticker", symbol, c.said(start, end), detail=company.name if company else None, confidence=confidence
            )

    for m in _TICKER_CUE.finditer(c.n):
        symbol = re.sub(r"[ .-]", "", m.group(1)).upper()
        add(symbol, m.start(1), m.end(1), "matched" if catalog.ticker(symbol) else "unsure")
    for m in _SPELLED.finditer(c.n):
        symbol = re.sub(r"[ .-]", "", m.group(1))
        if catalog.ticker(symbol):
            add(symbol, m.start(), m.end(), "matched")
    for m in _UPPER.finditer(c.n):
        if catalog.ticker(m.group(1)):
            add(m.group(1), m.start(), m.end(), "heard")
    for company in catalog.companies.values():
        for alias in sorted(company.aliases, key=len, reverse=True):
            if m := re.search(rf"\b{re.escape(alias)}\b", c.n):
                add(company.ticker, m.start(), m.end(), "matched")
                break
    out.entities.extend(found.values())


def _claims(c: _Ctx, out: RuleResult) -> None:
    for a, b in _sentences(c.norm):
        sentence = c.n[a:b]
        quote = c.said(a, b).strip()
        percent = _PERCENT.search(sentence)
        period = m.group(1).lower() if (m := _PERIOD.search(sentence)) else None
        if percent and (_UP.search(sentence) or _DOWN.search(sentence)) and not _FEE_CUE.search(sentence):
            sign = -1.0 if _DOWN.search(sentence) and not _UP.search(sentence) else 1.0
            metric = "return" if _RETURN_WORD.search(sentence) else "price_change"
            out.claims.append(RuleClaim(quote, metric, sign * _percent_value(percent.group(1)), "%", period))
        if _GUARANTEE.search(sentence) and not _NEGATED_GUARANTEE.search(sentence):
            value = _MULTIPLE[m.group(1).lower()] if (m := _MULTIPLE_RE.search(sentence)) else None
            if value is None and percent:
                value = _percent_value(percent.group(1))
            when = m.group(0) if (m := _BY_WHEN.search(sentence)) else period
            out.claims.append(RuleClaim(quote, "guarantee", value, "%" if value is not None else None, when))
        if percent and _EXPENSE_RATIO.search(sentence):
            # A fund's own cost is a checkable fact about the fund (unlike the firm's fee, an offer term).
            out.claims.append(RuleClaim(quote, "fee", _percent_value(percent.group(1)), "%", "a year" if _YEARLY.search(sentence) else None))


def extract_rules(text: str, catalog: Catalog) -> RuleResult:
    c = _Ctx(text)
    out = RuleResult()
    _tickers(c, catalog, out)
    _names(c, catalog, out)
    _prices(c, out)
    _quantities(c, out)
    _percents(c, out)
    _deadlines(c, out)
    _payments(c, out)
    _fees(c, out)
    _claims(c, out)
    return out


def event_sentences(text: str) -> list[str]:
    """Sentences with company-event cues; rules can't structure these, the LLM can."""
    c = _Ctx(text)
    return [c.said(a, b).strip() for a, b in _sentences(c.norm) if _EVENT_CUE.search(c.n[a:b])]


# --- Stage 2: Gemini, fuzzy cases only -------------------------------------------------


class LlmClaim(BaseModel):
    text: str
    metric: Literal["price_change", "return", "guarantee", "event", "fee", "other"]
    claimed_value: float | None
    unit: str | None
    period: str | None
    subject: str | None


class LlmEntity(BaseModel):
    kind: Literal["person", "firm", "ticker"]
    text: str


class ExtractionResult(BaseModel):
    claims: list[LlmClaim]
    entities: list[LlmEntity]


SYSTEM_PROMPT = """You read one sentence that a caller said on an unsolicited investment sales call.
Extract only what is explicitly said. Never add facts and never judge whether anything is true.
claims: factual statements that could be checked against data or records (price moves, returns,
guarantees, company events such as deals, contracts or approvals, fees). For each claim, copy the
exact words from the sentence into `text`. metric is one of price_change, return, guarantee, event,
fee, other. claimed_value is the number as said (40 for "up forty percent", 100 for "double"), else
null. unit is "%", "USD" or null. period is e.g. "this quarter" or "by Christmas", else null.
subject is the company or ticker the claim is about; use the current instrument for "it" or "the stock".
entities: person names, firm names, and stock tickers or company names; `text` must be the exact
words from the sentence. Return empty lists when there is nothing."""


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%$.&-]", " ", s.lower())).strip(" .")


def quoted(quote: str, text: str) -> bool:
    """True if the LLM's quote really appears in what was said."""
    q = _squash(quote)
    return bool(q) and q in _squash(text)


# --- The component ---------------------------------------------------------------------


class EntityExtractor:
    def __init__(
        self,
        bus: EventBus,
        catalog: Catalog,
        llm: LlmClient | None = None,
        *,
        call_id: str = "",
        source: str = "",
        drain_timeout: float = 9.0,
    ) -> None:
        self.bus = bus
        self.catalog = catalog
        self.llm = llm if llm is not None and llm.available else None
        self.call_id = call_id
        self.source = source
        self.drain_timeout = drain_timeout
        self._sub = bus.subscribe(UtteranceFinal, UtterancesClosed)
        self._pending: set[asyncio.Task] = set()
        self._subject: str | None = None
        self._caller_lines = 0
        self._person_known = False
        self._firm_known = False
        self._ids = 0

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, UtteranceFinal):
                self._handle(event.utterance)
            elif isinstance(event, UtterancesClosed):
                break
        if self._pending:
            done, pending = await asyncio.wait(self._pending, timeout=self.drain_timeout)
            for task in pending:
                task.cancel()
        self.bus.publish(EntitiesClosed())
        self._sub.close()

    def _id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}{self._ids}"

    def _entity(self, u: Utterance, e: RuleEntity) -> None:
        if e.kind == "ticker":
            self._subject = e.value
        if u.speaker == "caller":
            self._person_known |= e.kind == "person"
            self._firm_known |= e.kind == "firm"
        self.bus.publish(
            EntityDetected(
                entity=Entity(
                    id=self._id("e"),
                    kind=e.kind,
                    value=e.value,
                    text=e.text,
                    number=e.number,
                    unit=e.unit,
                    detail=e.detail,
                    utterance_id=u.id,
                    speaker=u.speaker,
                    t=u.t_start,
                    confidence=e.confidence,
                )
            )
        )

    def _claim(self, u: Utterance, text: str, metric, value, unit, period, subject) -> None:  # noqa: ANN001
        self.bus.publish(
            ClaimExtracted(
                claim=Claim(
                    id=self._id("c"),
                    text=text,
                    metric=metric,
                    claimed_value=value,
                    unit=unit,
                    period=period,
                    subject=subject or self._subject,
                    utterance_id=u.id,
                )
            )
        )

    def _handle(self, u: Utterance) -> None:
        started = time.perf_counter()
        result = extract_rules(u.text, self.catalog)
        for e in result.entities:
            self._entity(u, e)
        if u.speaker == "caller":
            self._caller_lines += 1
            for c in result.claims:
                self._claim(u, c.text, c.metric, c.claimed_value, c.unit, c.period, None)
            events = event_sentences(u.text)
            intro_names = self._caller_lines <= 3 and not (self._person_known and self._firm_known)
            if events or intro_names:
                if self.llm is not None:
                    task = asyncio.create_task(self._llm_stage(u, result, events))
                    self._pending.add(task)
                    task.add_done_callback(self._pending.discard)
                else:
                    self._fallback_events(u, events)
        record("extractor.rules", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source)

    def _fallback_events(self, u: Utterance, events: list[str]) -> None:
        for sentence in events:
            self._claim(u, sentence, "event", None, None, None, None)

    async def _llm_stage(self, u: Utterance, rules: RuleResult, events: list[str]) -> None:
        assert self.llm is not None
        prompt = f"Current instrument: {self._subject or 'unknown'}\nSentence: {u.text}"
        result = await self.llm.generate(
            system=SYSTEM_PROMPT, prompt=prompt, schema=ExtractionResult, stage="llm.extract", call_id=self.call_id
        )
        if result is None:
            self._fallback_events(u, events)  # rules-only: keep the event sentences as claims
            return
        rule_metrics = {c.metric for c in rules.claims}
        for c in result.claims:
            if not quoted(c.text, u.text) or (c.metric in rule_metrics and c.metric != "event"):
                continue  # the LLM may only point at words that were said; rules win on overlap
            self._claim(u, c.text.strip(), c.metric, c.claimed_value, c.unit, c.period, c.subject)
        rule_kinds = {e.kind for e in rules.entities}
        for e in result.entities:
            if e.kind in rule_kinds or not quoted(e.text, u.text):
                continue
            self._entity(u, self._resolve(e))

    def _resolve(self, e: LlmEntity) -> RuleEntity:
        text = e.text.strip()
        if e.kind == "ticker":
            symbol = re.sub(r"[ .-]", "", text).upper()
            company = self.catalog.ticker(symbol) or next(
                (c for c in self.catalog.companies.values() if text.lower() in (a.lower() for a in c.aliases)), None
            )
            if company:
                return RuleEntity("ticker", company.ticker, text, detail=company.name, confidence="matched")
            return RuleEntity("ticker", symbol, text, confidence="unsure")
        if e.kind == "firm":
            for firm in self.catalog.firms:
                if text.lower() in (a.lower() for a in firm.aliases):
                    return RuleEntity("firm", firm.name, text, confidence="matched")
        return RuleEntity(e.kind, text, text)
