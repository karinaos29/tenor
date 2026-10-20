"""Claim checker, fast lane: verdicts from data and arithmetic only.

- price_change / return: the claimed % vs. the provider's return for the matching window.
  "verified" if the sign matches and the gap is within max(3 points, 25% of the claim),
  otherwise "false". No data -> "unverifiable"; nothing is guessed.
- price: the offered price per share vs. the market quote (within 5%).
- event: keyword match against the company's news (last 90 days). No match -> "not_found";
  a match -> "unverifiable" with the headline, for the user to judge.
- guarantee: "unverifiable"; share prices can't be guaranteed.

Consumes: ClaimExtracted, OfferUpdated, UtteranceProgress, UtteranceFinal, OfferClosed.
Publishes: ClaimChecked, ChecksClosed.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable

from pipeline.bus import EventBus
from pipeline.events import (
    ChecksClosed,
    Claim,
    ClaimChecked,
    ClaimExtracted,
    OfferClosed,
    OfferUpdated,
    UtteranceFinal,
    UtteranceProgress,
)
from pipeline.latency import record
from providers.market import WINDOW_LABEL, MarketDataProvider, Window

log = logging.getLogger("tenor.checker")

PRICE_TOLERANCE_PCT = 5.0
_STOP = set(
    "a an the and or but with to of in on for at by from this that it its it's they them their is are was were be been "
    "just really very major big new signed deal stock shares company".split()
)


def window_for(period: str | None) -> Window | None:
    p = (period or "").lower()
    if "quarter" in p or "three months" in p or "3 months" in p:
        return "13w"
    if "this year" in p or "year to date" in p or "since january" in p:
        return "ytd"
    if "last year" in p or "past year" in p or "12 months" in p:
        return "52w"
    if "month" in p:
        return "mtd"
    if "week" in p:
        return "5d"
    if "today" in p:
        return "day"
    return None


def compare_pct(claimed: float, actual: float) -> bool:
    """True if the data supports the claim: same direction and close enough."""
    same_sign = (claimed >= 0) == (actual >= 0)
    return same_sign and abs(claimed - actual) <= max(3.0, 0.25 * abs(claimed))


def signed(x: float) -> str:
    return f"{x:+.1f}".replace(".0", "") if abs(x) >= 1 else f"{x:+.2f}"


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in _STOP}


class ClaimChecker:
    def __init__(
        self,
        bus: EventBus,
        market: MarketDataProvider,
        *,
        call_id: str = "",
        source: str = "",
        clock: Callable[[float], float | None] | None = None,
        drain_timeout: float = 5.0,
    ) -> None:
        self.bus = bus
        self.market = market
        self.call_id = call_id
        self.source = source
        self.clock = clock  # call time (s) -> time.monotonic() of that moment of audio
        self.drain_timeout = drain_timeout
        self._sub = bus.subscribe(ClaimExtracted, OfferUpdated, UtteranceFinal, UtteranceProgress, OfferClosed)
        self._ends: dict[str, float] = {}
        self._pending: set[asyncio.Task] = set()
        self._price_checked: set[tuple[str, float]] = set()

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, (UtteranceFinal, UtteranceProgress)):
                # Latest finalized word so far = the end of the sentence a claim came from.
                self._ends[event.utterance.id] = event.utterance.t_end
            elif isinstance(event, ClaimExtracted):
                self._spawn(event.claim)
            elif isinstance(event, OfferUpdated):
                self._maybe_check_price(event)
            elif isinstance(event, OfferClosed):
                # Not EntitiesClosed: the tracker may still turn the last entities into
                # offer.updated (and a price check). OfferClosed comes after all of them.
                break
        if self._pending:
            _, late = await asyncio.wait(self._pending, timeout=self.drain_timeout)
            for task in late:
                task.cancel()
        self.bus.publish(ChecksClosed())
        self._sub.close()

    def _spawn(self, claim: Claim) -> None:
        task = asyncio.create_task(self._check(claim))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def _maybe_check_price(self, event: OfferUpdated) -> None:
        offer = event.offer
        if not (offer.instrument and offer.price and offer.price.number is not None and offer.price.utterance_id):
            return
        symbol = offer.instrument.display.split(" · ")[0]
        key = (symbol, offer.price.number)
        if key in self._price_checked:
            return
        self._price_checked.add(key)
        self._spawn(
            Claim(
                id=f"price-{symbol}-{offer.price.number:g}",
                text=offer.price.said,
                metric="price",
                claimed_value=offer.price.number,
                unit="USD",
                subject=symbol,
                utterance_id=offer.price.utterance_id,
            )
        )

    async def _check(self, claim: Claim) -> None:
        started = time.perf_counter()
        try:
            status, actual, source, note = await self._verdict(claim)
        except Exception:  # noqa: BLE001 - a provider bug must not kill the call
            log.exception("check failed for %s", claim.id)
            status, actual, source, note = "unverifiable", None, None, "Couldn't check this right now"
        ms = (time.perf_counter() - started) * 1000
        checked = claim.model_copy(
            update={"status": status, "actual_value": actual, "source": source, "note": note, "checked_in_ms": round(ms, 1)}
        )
        self.bus.publish(ClaimChecked(claim=checked))
        record("check.claim", ms, call_id=self.call_id, source=self.source, metric=claim.metric, status=status)
        end = self._ends.get(claim.utterance_id)
        spoken_at = self.clock(end) if self.clock and end is not None else None
        if spoken_at is not None:
            # The demo metric: claim spoken (end of its audio) -> verdict on the bus.
            record("claim.flag_e2e", (time.monotonic() - spoken_at) * 1000, call_id=self.call_id, metric=claim.metric, status=status)

    async def _verdict(self, claim: Claim) -> tuple[str, float | None, str | None, str | None]:
        symbol = claim.subject
        if claim.metric == "guarantee":
            return "unverifiable", None, None, "Share prices can't be guaranteed"
        if not symbol:
            return "unverifiable", None, None, "Couldn't tell which company this is about"

        if claim.metric in ("price_change", "return"):
            window = window_for(claim.period)
            if window is None or claim.claimed_value is None:
                return "unverifiable", None, None, "Couldn't tell which time period this is about"
            returns = await self.market.returns(symbol)
            if returns is None or window not in returns.pct:
                return "unverifiable", None, None, "Couldn't get price data"
            actual = round(returns.pct[window], 1)
            status = "verified" if compare_pct(claim.claimed_value, actual) else "false"
            return status, actual, returns.source, WINDOW_LABEL[window]

        if claim.metric == "price":
            quote = await self.market.quote(symbol)
            if quote is None or claim.claimed_value is None:
                return "unverifiable", None, None, "Couldn't get the market price"
            gap = (claim.claimed_value - quote.price) / quote.price * 100
            status = "verified" if abs(gap) <= PRICE_TOLERANCE_PCT else "false"
            note = "close to the market price" if status == "verified" else f"{abs(gap):.1f}% {'above' if gap > 0 else 'below'} the market price"
            return status, round(quote.price, 4), quote.source, note

        if claim.metric == "event":
            news = await self.market.news(symbol, days=90)
            if news is None:
                return "unverifiable", None, None, "Couldn't check the news"
            wanted = keywords(claim.text)
            for item in news:
                if len(wanted & keywords(item.headline)) >= 2:
                    return "unverifiable", None, item.source, f"Possibly related news: “{item.headline}” ({item.published})"
            return "not_found", None, "News, last 90 days", f"No news about this for {symbol} in the last 90 days"

        if claim.metric == "fee":
            return "unverifiable", None, None, "Fund cost data isn't available in this prototype"
        return "unverifiable", None, None, None
