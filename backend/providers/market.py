"""Market data behind one interface: Finnhub for real tickers, fixtures for fictional ones.

Every call has a timeout and returns None on any failure (no key, timeout, HTTP error,
missing field). The checker turns None into "couldn't verify"; nothing is guessed.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

import httpx

from pipeline.latency import record
from providers.catalog import FIXTURES, Catalog

log = logging.getLogger("tenor.market")

Window = Literal["day", "5d", "mtd", "13w", "ytd", "52w"]

WINDOW_LABEL: dict[Window, str] = {
    "day": "today",
    "5d": "last 5 days",
    "mtd": "this month so far",
    "13w": "last 13 weeks",
    "ytd": "this year so far",
    "52w": "last 52 weeks",
}

# Finnhub `stock/metric` field per window ("day" comes from the quote).
FINNHUB_RETURN_FIELD: dict[Window, str] = {
    "5d": "5DayPriceReturnDaily",
    "mtd": "monthToDatePriceReturnDaily",
    "13w": "13WeekPriceReturnDaily",
    "ytd": "yearToDatePriceReturnDaily",
    "52w": "52WeekPriceReturnDaily",
}


@dataclass(frozen=True)
class Quote:
    price: float
    day_change_pct: float | None
    source: str


@dataclass(frozen=True)
class Returns:
    pct: dict[Window, float]
    source: str


@dataclass(frozen=True)
class Profile:
    name: str
    exchange: str | None
    ipo: str | None
    market_cap_musd: float | None
    source: str


@dataclass(frozen=True)
class NewsItem:
    headline: str
    source: str
    published: date


class MarketDataProvider(Protocol):
    async def quote(self, symbol: str) -> Quote | None: ...
    async def returns(self, symbol: str) -> Returns | None: ...
    async def profile(self, symbol: str) -> Profile | None: ...
    async def news(self, symbol: str, days: int = 90) -> list[NewsItem] | None: ...


class FixtureProvider:
    """Invented test data for fictional companies (fixtures/companies/*.json, key "market")."""

    SOURCE = "Test data · fictional company"

    def __init__(self, catalog: Catalog) -> None:
        import json

        self._data: dict[str, dict] = {}
        for path in sorted((FIXTURES / "companies").glob("*.json")):
            entry = json.loads(path.read_text())
            if "market" in entry:
                self._data[entry["ticker"].upper()] = {**entry["market"], "name": entry["name"]}
        self.catalog = catalog

    def has(self, symbol: str) -> bool:
        return symbol.upper() in self._data

    async def quote(self, symbol: str) -> Quote | None:
        d = self._data.get(symbol.upper())
        return Quote(d["price"], d.get("day_change_pct"), self.SOURCE) if d else None

    async def returns(self, symbol: str) -> Returns | None:
        d = self._data.get(symbol.upper())
        if not d:
            return None
        pct = dict(d.get("returns_pct", {}))
        if d.get("day_change_pct") is not None:
            pct["day"] = d["day_change_pct"]
        return Returns(pct, self.SOURCE)  # type: ignore[arg-type]

    async def profile(self, symbol: str) -> Profile | None:
        d = self._data.get(symbol.upper())
        if not d:
            return None
        p = d.get("profile", {})
        return Profile(d["name"], p.get("exchange"), p.get("ipo"), p.get("market_cap_musd"), self.SOURCE)

    async def news(self, symbol: str, days: int = 90) -> list[NewsItem] | None:
        d = self._data.get(symbol.upper())
        if d is None:
            return None
        return [NewsItem(n["headline"], n.get("source", self.SOURCE), date.fromisoformat(n["date"])) for n in d.get("news", [])]


class FinnhubProvider:
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, *, timeout_s: float = 3.0, cache_ttl_s: float = 300.0) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.cache_ttl_s = cache_ttl_s
        self._cache: dict[tuple, tuple[float, object]] = {}

    async def _get(self, path: str, **params: object) -> object | None:
        if not self.api_key:
            return None
        key = (path, tuple(sorted(params.items())))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl_s:
            return hit[1]
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.get(f"{self.BASE}/{path}", params={**params, "token": self.api_key})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            record("provider.finnhub", (time.perf_counter() - started) * 1000, path=path, ok=False, error=type(e).__name__)
            log.warning("finnhub %s failed: %s", path, type(e).__name__)
            return None
        record("provider.finnhub", (time.perf_counter() - started) * 1000, path=path, ok=True)
        self._cache[key] = (time.monotonic(), data)
        return data

    async def quote(self, symbol: str) -> Quote | None:
        d = await self._get("quote", symbol=symbol)
        if not isinstance(d, dict) or not d.get("c"):
            return None  # Finnhub returns zeros for unknown symbols
        return Quote(float(d["c"]), d.get("dp"), "Finnhub · quote")

    async def returns(self, symbol: str) -> Returns | None:
        d = await self._get("stock/metric", symbol=symbol, metric="all")
        metric = d.get("metric") if isinstance(d, dict) else None
        if not isinstance(metric, dict):
            return None
        pct: dict[Window, float] = {w: float(metric[f]) for w, f in FINNHUB_RETURN_FIELD.items() if metric.get(f) is not None}
        quote = await self.quote(symbol)
        if quote and quote.day_change_pct is not None:
            pct["day"] = float(quote.day_change_pct)
        return Returns(pct, "Finnhub · price returns") if pct else None

    async def profile(self, symbol: str) -> Profile | None:
        d = await self._get("stock/profile2", symbol=symbol)
        if not isinstance(d, dict) or not d.get("name"):
            return None
        return Profile(d["name"], d.get("exchange"), d.get("ipo"), d.get("marketCapitalization"), "Finnhub · company profile")

    async def news(self, symbol: str, days: int = 90) -> list[NewsItem] | None:
        today = datetime.now(UTC).date()
        d = await self._get("company-news", symbol=symbol, **{"from": str(today - timedelta(days=days)), "to": str(today)})
        if not isinstance(d, list):
            return None
        items = []
        for n in d:
            try:
                items.append(NewsItem(n["headline"], n.get("source") or "Finnhub", datetime.fromtimestamp(n["datetime"], UTC).date()))
            except (KeyError, TypeError, ValueError):
                continue
        return items


class RoutedMarketData:
    """Fictional tickers go to fixtures (never to a real API); everything else to Finnhub."""

    def __init__(self, fixtures: FixtureProvider, live: MarketDataProvider | None) -> None:
        self.fixtures = fixtures
        self.live = live

    def _pick(self, symbol: str) -> MarketDataProvider | None:
        company = self.fixtures.catalog.ticker(symbol)
        if (company and company.fictional) or self.fixtures.has(symbol):
            return self.fixtures
        return self.live

    async def quote(self, symbol: str) -> Quote | None:
        p = self._pick(symbol)
        return await p.quote(symbol) if p else None

    async def returns(self, symbol: str) -> Returns | None:
        p = self._pick(symbol)
        return await p.returns(symbol) if p else None

    async def profile(self, symbol: str) -> Profile | None:
        p = self._pick(symbol)
        return await p.profile(symbol) if p else None

    async def news(self, symbol: str, days: int = 90) -> list[NewsItem] | None:
        p = self._pick(symbol)
        return await p.news(symbol, days) if p else None
