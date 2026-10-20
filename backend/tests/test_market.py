"""Market data providers: fixtures, Finnhub (httpx mocked, no network), and routing."""

import asyncio

import httpx
import pytest

from providers import market
from providers.catalog import default_catalog
from providers.market import FinnhubProvider, FixtureProvider, RoutedMarketData
from tests.m3_helpers import latency_entries

REAL_CLIENT = httpx.AsyncClient


def run(coro):
    return asyncio.run(coro)


def mock_finnhub(monkeypatch, handler):
    """Route every httpx.AsyncClient inside providers.market through a MockTransport."""
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        return REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(market.httpx, "AsyncClient", factory)
    return seen


# --- FixtureProvider ----------------------------------------------------------------


def fixtures() -> FixtureProvider:
    return FixtureProvider(default_catalog())


def test_fixture_quote_returns_profile_news_for_kstl():
    p = fixtures()
    q = run(p.quote("kstl"))
    assert q.price == 0.38 and q.source == FixtureProvider.SOURCE
    r = run(p.returns("KSTL"))
    assert r.pct["13w"] == -12.5 and r.pct["day"] == -1.3 and r.pct["52w"] == -48.0
    prof = run(p.profile("KSTL"))
    assert prof.name == "Kestrel Motors" and prof.exchange == "OTC (unlisted)"
    assert run(p.news("KSTL")) == []


def test_fixture_unknown_symbol_is_none_everywhere():
    p = fixtures()
    assert p.has("KSTL") and not p.has("ZZZZ")
    for call in (p.quote, p.returns, p.profile, p.news):
        assert run(call("ZZZZ")) is None


# --- FinnhubProvider ----------------------------------------------------------------

QUOTE = {"c": 512.3, "dp": 0.8, "d": 4.0, "h": 0, "l": 0, "o": 0, "pc": 0}
METRIC = {
    "metric": {
        "5DayPriceReturnDaily": 1.5,
        "monthToDatePriceReturnDaily": 2.5,
        "13WeekPriceReturnDaily": 7.25,
        "yearToDatePriceReturnDaily": 11.0,
        "52WeekPriceReturnDaily": 20.5,
    }
}


def handler_ok(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/quote"):
        return httpx.Response(200, json=QUOTE)
    if path.endswith("/stock/metric"):
        return httpx.Response(200, json=METRIC)
    return httpx.Response(404)


def test_finnhub_quote_success(monkeypatch):
    seen = mock_finnhub(monkeypatch, handler_ok)
    q = run(FinnhubProvider("k").quote("VOO"))
    assert q.price == 512.3 and q.day_change_pct == 0.8 and q.source == "Finnhub · quote"
    assert seen[0].url.params["symbol"] == "VOO" and seen[0].url.params["token"] == "k"
    assert latency_entries("provider.finnhub")[-1]["ok"] is True


def test_finnhub_all_zero_quote_means_unknown_symbol(monkeypatch):
    mock_finnhub(monkeypatch, lambda r: httpx.Response(200, json={"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0}))
    assert run(FinnhubProvider("k").quote("NOPE")) is None


def test_finnhub_metric_maps_to_windows_and_adds_day(monkeypatch):
    mock_finnhub(monkeypatch, handler_ok)
    r = run(FinnhubProvider("k").returns("VOO"))
    assert r.pct == {"5d": 1.5, "mtd": 2.5, "13w": 7.25, "ytd": 11.0, "52w": 20.5, "day": 0.8}
    assert r.source == "Finnhub · price returns"


def test_finnhub_metric_without_return_fields_is_none(monkeypatch):
    mock_finnhub(monkeypatch, lambda r: httpx.Response(200, json={"metric": {"beta": 1.0}} if "metric" in r.url.path else {"c": 0}))
    assert run(FinnhubProvider("k").returns("VOO")) is None


def test_finnhub_http_403_is_none_and_logged(monkeypatch):
    mock_finnhub(monkeypatch, lambda r: httpx.Response(403, json={"error": "no access"}))
    assert run(FinnhubProvider("k").quote("VOO")) is None
    row = latency_entries("provider.finnhub")[-1]
    assert row["ok"] is False and row["error"] == "HTTPStatusError" and row["path"] == "quote"


def test_finnhub_timeout_is_none(monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("too slow", request=request)

    mock_finnhub(monkeypatch, slow)
    assert run(FinnhubProvider("k", timeout_s=0.1).quote("VOO")) is None
    assert latency_entries("provider.finnhub")[-1]["ok"] is False


def test_finnhub_bad_json_is_none(monkeypatch):
    mock_finnhub(monkeypatch, lambda r: httpx.Response(200, content=b"<html>oops"))
    assert run(FinnhubProvider("k").quote("VOO")) is None


def test_finnhub_without_key_makes_no_request(monkeypatch):
    seen = mock_finnhub(monkeypatch, handler_ok)
    p = FinnhubProvider("")
    assert run(p.quote("VOO")) is None and run(p.returns("VOO")) is None
    assert run(p.profile("VOO")) is None and run(p.news("VOO")) is None
    assert seen == []


def test_finnhub_cache_hit_avoids_second_request(monkeypatch):
    seen = mock_finnhub(monkeypatch, handler_ok)
    p = FinnhubProvider("k")

    async def twice():
        return await p.quote("VOO"), await p.quote("VOO")

    a, b = run(twice())
    assert a == b and len(seen) == 1


def test_finnhub_failures_are_not_cached(monkeypatch):
    seen = mock_finnhub(monkeypatch, lambda r: httpx.Response(500))
    p = FinnhubProvider("k")

    async def twice():
        await p.quote("VOO")
        await p.quote("VOO")

    run(twice())
    assert len(seen) == 2


def test_finnhub_news_parses_and_skips_bad_items(monkeypatch):
    items = [{"headline": "VOO hits record", "source": "Wire", "datetime": 1_760_000_000}, {"nonsense": 1}]
    mock_finnhub(monkeypatch, lambda r: httpx.Response(200, json=items))
    news = run(FinnhubProvider("k").news("VOO"))
    assert [n.headline for n in news] == ["VOO hits record"] and news[0].source == "Wire"


# --- RoutedMarketData ---------------------------------------------------------------


class ExplodingLive:
    async def _boom(self, *a, **k):
        raise AssertionError("live provider must not be called")

    quote = returns = profile = news = _boom


class RecordingLive:
    def __init__(self):
        self.calls = []

    async def quote(self, symbol):
        self.calls.append(symbol)
        return market.Quote(500.0, 0.1, "live")

    async def returns(self, symbol):
        return None

    profile = news = returns


def test_fictional_kstl_never_reaches_live():
    routed = RoutedMarketData(fixtures(), ExplodingLive())
    assert run(routed.quote("KSTL")).price == 0.38
    assert run(routed.returns("KSTL")).pct["13w"] == -12.5
    assert run(routed.profile("KSTL")).name == "Kestrel Motors"
    assert run(routed.news("KSTL")) == []


def test_real_voo_goes_to_live():
    live = RecordingLive()
    routed = RoutedMarketData(fixtures(), live)
    assert run(routed.quote("VOO")).source == "live" and live.calls == ["VOO"]


def test_real_symbol_without_live_is_none():
    routed = RoutedMarketData(fixtures(), None)
    assert run(routed.quote("VOO")) is None and run(routed.returns("VOO")) is None
    assert run(routed.profile("VOO")) is None and run(routed.news("VOO")) is None


@pytest.mark.finnhub
def test_live_finnhub_voo_quote_and_13w_return():
    from app.config import get_settings

    key = get_settings().finnhub_api_key
    if not key:
        pytest.skip("FINNHUB_API_KEY not set")
    p = FinnhubProvider(key, timeout_s=8.0)

    async def main():
        return await p.quote("VOO"), await p.returns("VOO")

    quote, returns = run(main())
    assert quote is not None and quote.price > 50
    assert returns is not None and "13w" in returns.pct and -80 < returns.pct["13w"] < 200
