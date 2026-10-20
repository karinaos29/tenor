"""Shared helpers for the M3 (verify) tests: fake market data, bus collection, latency log."""

import asyncio
import json

from pipeline import latency
from pipeline.events import Claim, Entity, Term
from providers.market import NewsItem, Profile, Quote, Returns


def latency_entries(stage: str | None = None) -> list[dict]:
    path = latency.LOG_PATH
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return [r for r in rows if stage is None or r["stage"] == stage]


class FakeMarket:
    """Configurable MarketDataProvider. `delay` slows every call; `boom` makes them raise."""

    def __init__(self, *, quote=None, returns=None, profile=None, news=None, delay=0.0, boom=False) -> None:
        self._quote, self._returns, self._profile, self._news = quote, returns, profile, news
        self.delay, self.boom = delay, boom
        self.calls: list[str] = []

    async def _go(self, name):
        self.calls.append(name)
        if self.boom:
            raise RuntimeError("provider bug")
        if self.delay:
            await asyncio.sleep(self.delay)

    async def quote(self, symbol):
        await self._go("quote")
        return self._quote

    async def returns(self, symbol):
        await self._go("returns")
        return self._returns

    async def profile(self, symbol):
        await self._go("profile")
        return self._profile

    async def news(self, symbol, days=90):
        await self._go("news")
        return self._news


def kstl_market(**over) -> FakeMarket:
    base = dict(
        quote=Quote(0.38, -1.3, "Test quote"),
        returns=Returns({"13w": -12.5, "52w": -48.0, "day": -1.3}, "Test returns"),
        profile=Profile("Kestrel Motors", "OTC (unlisted)", None, None, "Test profile"),
        news=[],
    )
    base.update(over)
    return FakeMarket(**base)


def headline(text: str) -> NewsItem:
    from datetime import date

    return NewsItem(text, "Test wire", date(2026, 9, 1))


def make_claim(id="c1", metric="price_change", value=40.0, period="this quarter", subject="KSTL", text="it is up forty percent this quarter", utt="u1", **kw) -> Claim:
    return Claim(id=id, text=text, metric=metric, claimed_value=value, unit="%", period=period, subject=subject, utterance_id=utt, **kw)


def make_entity(kind, value, *, confidence="heard", id="e1") -> Entity:
    return Entity(id=id, kind=kind, value=value, text=value, utterance_id="u1", speaker="caller", t=1.0, confidence=confidence)


def term(display, number=None, utt="u1") -> Term:
    return Term(display=display, number=number, said=display, utterance_id=utt)
