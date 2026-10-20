"""ClaimChecker on a real bus with fake market data: verdicts come from data and arithmetic."""

import asyncio
import time

import pytest

from pipeline.bus import EventBus
from pipeline.checker import ClaimChecker, compare_pct, window_for
from pipeline.events import (
    ChecksClosed,
    ClaimChecked,
    ClaimExtracted,
    OfferClosed,
    Offer,
    OfferUpdated,
    Utterance,
    UtteranceFinal,
)
from providers.catalog import default_catalog
from providers.market import FixtureProvider, Returns
from tests.m3_helpers import headline, kstl_market, latency_entries, make_claim, term


def check(events, market, **kw):
    """Publish `events`, close, and return (checked claims, all events seen by a spy)."""

    async def main():
        bus = EventBus()
        checker = ClaimChecker(bus, market, **kw)
        spy = bus.subscribe(ClaimChecked, ChecksClosed, OfferClosed)
        task = asyncio.create_task(checker.run())
        for e in events:
            bus.publish(e)
        bus.publish(OfferClosed())  # the checker stops after the tracker is done
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    return asyncio.run(main())


def verdicts(seen):
    return [e.claim for e in seen if isinstance(e, ClaimChecked)]


def one(claim, market=None, **kw):
    return verdicts(check([ClaimExtracted(claim=claim)], market or kstl_market(), **kw))[0]


# --- pure helpers -------------------------------------------------------------------


@pytest.mark.parametrize(
    "period,window",
    [
        ("this quarter", "13w"), ("the last three months", "13w"), ("3 months", "13w"),
        ("this year", "ytd"), ("year to date", "ytd"), ("since January", "ytd"),
        ("last year", "52w"), ("past year", "52w"), ("12 months", "52w"),
        ("this month", "mtd"), ("this week", "5d"), ("today", "day"),
        ("by Christmas", None), (None, None), ("", None),
    ],
)  # fmt: skip
def test_window_for(period, window):
    assert window_for(period) == window


@pytest.mark.parametrize(
    "claimed,actual,ok",
    [
        (40, -12.5, False),  # far apart and opposite
        (10, -10, False),  # sign mismatch
        (-5, 5, False),
        (10, 12.5, True),  # within 3 points
        (40, 31, True),  # within 25% (10) of 40
        (40, 29, False),  # gap 11 > 10
        (4, 7, True),  # exactly 3 points
        (4, 7.5, False),
        (0, 0, True),
        (0, 2, True),  # zero counts as non-negative
        (-20, -14, False),  # gap 6 > max(3, 5)
        (-20, -16, True),
    ],
)  # fmt: skip
def test_compare_pct(claimed, actual, ok):
    assert compare_pct(claimed, actual) is ok


# --- price_change / return ----------------------------------------------------------


def test_price_change_false_with_actual_note_and_source():
    c = one(make_claim())
    assert c.status == "false" and c.actual_value == -12.5
    assert c.note == "last 13 weeks" and c.source == "Test returns"
    assert c.claimed_value == 40


def test_price_change_verified_when_close():
    c = one(make_claim(value=-12.0))
    assert c.status == "verified" and c.actual_value == -12.5


def test_return_metric_is_checked_like_price_change():
    assert one(make_claim(metric="return", value=-12.5, period="the last three months")).status == "verified"


def test_unknown_period_is_unverifiable():
    c = one(make_claim(period="by Christmas"))
    assert c.status == "unverifiable" and c.actual_value is None and "time period" in c.note


def test_missing_claimed_value_is_unverifiable():
    assert one(make_claim(value=None)).status == "unverifiable"


def test_no_data_is_unverifiable():
    c = one(make_claim(), kstl_market(returns=None))
    assert c.status == "unverifiable" and c.actual_value is None and c.note == "Couldn't get price data"


def test_window_missing_from_returns_is_unverifiable():
    assert one(make_claim(), kstl_market(returns=Returns({"5d": 1.0}, "t"))).status == "unverifiable"


def test_provider_exception_is_unverifiable_not_a_crash():
    c = one(make_claim(), kstl_market(boom=True))
    assert c.status == "unverifiable" and c.note == "Couldn't check this right now"


# --- price --------------------------------------------------------------------------


def offer_with_price(price=0.42, symbol="KSTL"):
    return Offer(instrument=term(f"{symbol} · Kestrel Motors"), price=term("$0.42 a share", price))


def test_price_claim_from_offer_is_false_and_not_rechecked():
    ev = OfferUpdated(offer=offer_with_price())
    out = verdicts(check([ev, ev, OfferUpdated(offer=offer_with_price())], kstl_market()))
    assert len(out) == 1
    c = out[0]
    assert c.metric == "price" and c.status == "false" and c.id == "price-KSTL-0.42"
    assert c.claimed_value == 0.42 and c.actual_value == 0.38 and c.note == "10.5% above the market price"


def test_new_price_is_checked_again():
    out = verdicts(check([OfferUpdated(offer=offer_with_price(0.42)), OfferUpdated(offer=offer_with_price(0.39))], kstl_market()))
    assert sorted((c.claimed_value, c.status) for c in out) == [(0.39, "verified"), (0.42, "false")]


def test_price_below_market_is_worded_below():
    out = verdicts(check([OfferUpdated(offer=offer_with_price(0.30))], kstl_market()))
    assert out[0].status == "false" and out[0].note.endswith("below the market price")


def test_offer_without_price_instrument_or_utterance_makes_no_claim():
    bare = Offer(instrument=term("KSTL · Kestrel Motors"))
    no_utt = Offer(instrument=term("KSTL · K"), price=term("$1", 1.0, utt=None))
    assert verdicts(check([OfferUpdated(offer=bare), OfferUpdated(offer=no_utt)], kstl_market())) == []


def test_price_with_no_quote_is_unverifiable():
    out = verdicts(check([OfferUpdated(offer=offer_with_price())], kstl_market(quote=None)))
    assert out[0].status == "unverifiable"


def test_price_with_fixture_provider_end_to_end():
    out = verdicts(check([OfferUpdated(offer=offer_with_price())], FixtureProvider(default_catalog())))
    assert out[0].status == "false" and out[0].source == FixtureProvider.SOURCE


# --- event / guarantee / subject ----------------------------------------------------

EVENT = dict(id="ev", metric="event", value=None, period=None, text="They just signed a deal with a major carmaker")


def test_event_with_no_news_is_not_found():
    c = one(make_claim(**EVENT), kstl_market(news=[]))
    assert c.status == "not_found" and "last 90 days" in c.note


def test_event_with_matching_headline_is_unverifiable_and_quotes_it():
    news = [headline("Kestrel announced partnership with carmaker"), headline("Weather in Ohio")]
    claim = make_claim(**{**EVENT, "text": "They announced a partnership with a major carmaker"})
    c = one(claim, kstl_market(news=news))
    assert c.status == "unverifiable" and "Kestrel announced partnership with carmaker" in c.note
    assert c.source == "Test wire"


def test_event_with_one_shared_keyword_is_still_not_found():
    c = one(make_claim(**EVENT), kstl_market(news=[headline("Carmaker opens a new plant")]))
    assert c.status == "not_found"


def test_event_with_news_unavailable_is_unverifiable():
    c = one(make_claim(**EVENT), kstl_market(news=None))
    assert c.status == "unverifiable" and c.note == "Couldn't check the news"


def test_guarantee_is_unverifiable():
    c = one(make_claim(id="g", metric="guarantee", value=100, period="by Christmas"))
    assert c.status == "unverifiable" and "guaranteed" in c.note


def test_no_subject_is_unverifiable():
    c = one(make_claim(subject=None))
    assert c.status == "unverifiable" and "which company" in c.note


def test_fee_is_unverifiable():
    assert one(make_claim(id="f", metric="fee", value=0.03, subject="VOO")).status == "unverifiable"


# --- bookkeeping --------------------------------------------------------------------


def test_checked_in_ms_and_latency_record():
    c = one(make_claim(), call_id="c9", source="replay")
    assert c.checked_in_ms is not None and c.checked_in_ms >= 0
    rows = latency_entries("check.claim")
    assert rows and rows[-1]["metric"] == "price_change" and rows[-1]["status"] == "false" and rows[-1]["call_id"] == "c9"


def utterance(id="u1", t_end=5.0):
    return UtteranceFinal(utterance=Utterance(id=id, speaker="caller", speaker_index=1, text="x", t_start=t_end - 1, t_end=t_end, is_final=True))


def test_flag_e2e_recorded_when_clock_and_t_end_known():
    seen = []

    def clock(t):
        seen.append(t)
        return time.monotonic() - 0.25

    check([utterance(t_end=5.0), ClaimExtracted(claim=make_claim())], kstl_market(), clock=clock, call_id="c1")
    assert seen == [5.0]
    rows = latency_entries("claim.flag_e2e")
    assert len(rows) == 1 and rows[0]["ms"] >= 250 and rows[0]["status"] == "false"


def test_flag_e2e_not_recorded_without_clock_or_unknown_utterance():
    check([utterance(), ClaimExtracted(claim=make_claim())], kstl_market())
    check([ClaimExtracted(claim=make_claim())], kstl_market(), clock=lambda t: time.monotonic())  # no UtteranceFinal seen
    check([utterance(), ClaimExtracted(claim=make_claim())], kstl_market(), clock=lambda t: None)  # not real time
    assert latency_entries("claim.flag_e2e") == []


def test_checks_closed_follows_offer_closed_even_with_slow_check():
    seen = check([ClaimExtracted(claim=make_claim())], kstl_market(delay=5.0), drain_timeout=0.05)
    kinds = [e.type for e in seen]
    assert kinds.index("offer.closed") < kinds.index("checks.closed")
    assert kinds[-1] == "checks.closed"
    assert verdicts(seen) == []  # the slow check was cancelled, not half-published


def test_checks_closed_waits_for_pending_checks_within_timeout():
    seen = check([ClaimExtracted(claim=make_claim())], kstl_market(delay=0.05), drain_timeout=2.0)
    kinds = [e.type for e in seen]
    assert kinds.index("claim.checked") < kinds.index("checks.closed")
