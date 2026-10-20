"""Suggestion engine + risk score: scored rules, fully deterministic.

Merges checked claims, research, and offer changes (tactics join in M4) into ranked
suggestions: "say this" lines (fixed first-person templates) and research cards. At most
four are visible, highest priority first; the rest are kept as `earlier` for the memo.
"Say this" lines expire after `say_ttl_s` unless the same signal fires again.

The risk score is a sum of listed reasons, capped at 100. The LLM is not involved.

Consumes: ClaimChecked, ResearchReady, OfferUpdated, OfferChanged, ChecksClosed, ResearchClosed.
Publishes: SuggestionsUpdated, RiskUpdated.
"""

import asyncio
from datetime import timedelta

from pipeline.bus import EventBus
from pipeline.events import (
    ChecksClosed,
    Claim,
    ClaimChecked,
    OfferChanged,
    OfferUpdated,
    ResearchClosed,
    ResearchItem,
    ResearchReady,
    RiskLevel,
    RiskReason,
    RiskUpdated,
    Suggestion,
    SuggestionsUpdated,
    utc_now,
)

MAX_VISIBLE = 4
MAX_SAY_THIS = 2  # what to do now (top) + evidence (research) below, as in the wireframe
RISKY_PAYMENTS = {"Bank transfer", "Wire transfer", "Crypto", "Gift cards"}
SAME_DAY = ("today", "tonight", "this afternoon", "this evening", "end of day")

PERIOD_PHRASE = {
    "last 13 weeks": "Over the last three months",
    "this year so far": "This year so far",
    "last 52 weeks": "Over the past year",
    "this month so far": "This month so far",
    "last 5 days": "Over the last five days",
    "today": "Today",
}


def level_for(score: int) -> RiskLevel:
    if score < 25:
        return "low"
    if score < 50:
        return "medium"
    if score < 75:
        return "high"
    return "critical"


class SuggestionEngine:
    def __init__(self, bus: EventBus, *, call_id: str = "", say_ttl_s: float = 120.0, tick_s: float = 2.0) -> None:
        self.bus = bus
        self.call_id = call_id
        self.say_ttl = timedelta(seconds=say_ttl_s)
        self.tick_s = tick_s
        self._sub = bus.subscribe(ChecksClosed, ClaimChecked, OfferChanged, OfferUpdated, ResearchClosed, ResearchReady)
        self._items: dict[str, Suggestion] = {}
        self._expired: dict[str, Suggestion] = {}
        self._reasons: dict[str, RiskReason] = {}
        self._firm_unregistered = False
        self._payment: str | None = None
        self._closed: set[str] = set()
        self._last: tuple | None = None
        self._last_risk: tuple | None = None
        # Risk is shown only once something has been checked, so "Low" never means "nothing looked at yet".
        self._assessed = False

    async def run(self) -> None:
        events = self._sub.__aiter__()
        while self._closed != {"checks", "research"}:
            try:
                event = await asyncio.wait_for(events.__anext__(), timeout=self.tick_s)
            except TimeoutError:
                self._expire()
                continue
            except StopAsyncIteration:
                break
            if isinstance(event, ClaimChecked):
                self._assessed |= event.claim.status != "checking"
                self._on_claim(event.claim)
            elif isinstance(event, ResearchReady):
                self._assessed |= event.item.status == "ready"
                self._on_research(event.item)
            elif isinstance(event, OfferUpdated):
                self._on_offer(event)
            elif isinstance(event, OfferChanged):
                self._on_change(event)
            elif isinstance(event, ChecksClosed):
                self._closed.add("checks")
            elif isinstance(event, ResearchClosed):
                self._closed.add("research")
            self._expire()
        self._publish(force=True)
        self._sub.close()

    # --- rules ------------------------------------------------------------------------

    def _say(self, key: str, title: str, text: str, priority: int, reason: str, source: str = "") -> None:
        now = utc_now()
        self._expired.pop(key, None)
        self._items[key] = Suggestion(
            id=key, kind="say_this", title=title, text=text, priority=priority, status="ready",
            reason=reason, source=source, checked_at=now, expires_at=now + self.say_ttl,
        )  # fmt: skip

    def _risk(self, key: str, label: str, points: int) -> None:
        self._reasons[key] = RiskReason(label=label, points=points)

    def _on_claim(self, c: Claim) -> None:
        if c.status == "false" and c.metric in ("price_change", "return") and c.actual_value is not None:
            when = PERIOD_PHRASE.get(c.note or "", "Recently")
            direction = "up" if c.actual_value >= 0 else "down"
            text = f"That's not what I see. {when} {c.subject} went {direction} {abs(c.actual_value):g}%. Can you send me your figures in writing?"
            self._say(f"say-claim-{c.id}", "A claim doesn't match data", text, 100, f"The caller said {c.claimed_value:+g}%, the data says {c.actual_value:+g}%.", c.source or "")
            self._risk(f"claim-{c.id}", "A claim doesn't match data", 30)
        elif c.status == "false" and c.metric == "price" and c.actual_value is not None and c.claimed_value is not None:
            text = f"The market price I can see is ${c.actual_value:.2f}, not ${c.claimed_value:.2f}. Why is yours different?"
            self._say(f"say-price-{c.subject}", "The price doesn't match the market", text, 70, c.note or "", c.source or "")
            self._risk("price", "The offered price doesn't match the market price", 10)
        elif c.metric == "guarantee" and c.status != "checking":
            text = "No one can guarantee a share price. Can you put that promise in writing?"
            self._say("say-guarantee", "A guarantee was promised", text, 85, "Share prices can go down as well as up.")
            self._risk("guarantee", "A guaranteed return was promised", 15)
        elif c.metric == "event" and c.status == "not_found":
            text = "I can't find any news about that. Where can I read about it myself?"
            self._say(f"say-event-{c.id}", "No evidence for this news", text, 75, c.note or "", c.source or "")
            self._risk(f"event-{c.id}", "No evidence for a company event the caller described", 10)

    def _on_research(self, item: ResearchItem) -> None:
        priority = 50 if item.finding == "not_registered" else 45
        self._items[item.id] = Suggestion(
            id=item.id, kind="research", title=item.title, text=item.summary, priority=priority,
            status="prefetching" if item.status == "prefetching" else "ready",
            reason="Checked while you talk", source=item.source, checked_at=item.checked_at,
        )  # fmt: skip
        if item.finding == "not_registered" and not self._firm_unregistered:
            self._firm_unregistered = True
            text = "Which regulator are you registered with? I'd like to check your registration number first."
            self._say("say-register", f"{item.subject} isn't in the register", text, 90, item.summary, item.source)
            self._risk("register", "The firm isn't in the register", 25)
            self._payment_rule()

    def _on_offer(self, event: OfferUpdated) -> None:
        offer = event.offer
        if offer.deadline and offer.deadline.display.lower().startswith(SAME_DAY):
            text = "I don't make decisions on the same day. Can you email me the details first?"
            self._say("say-deadline", "A same-day deadline", text, 80, f"The caller set a deadline: {offer.deadline.display}.")
            self._risk("deadline", "The deadline is today", 10)
        if offer.payment:
            self._payment = offer.payment.display
            self._payment_rule()

    def _payment_rule(self) -> None:
        if self._payment in RISKY_PAYMENTS and self._firm_unregistered:
            text = "I only pay through my own bank, after I've checked your registration."
            self._say("say-payment", f"Payment by {self._payment.lower()}", text, 65, "Money sent this way is hard to get back.")
            self._risk("payment", f"Payment by {self._payment.lower()} to a firm that isn't registered", 10)

    def _on_change(self, event: OfferChanged) -> None:
        c = event.change
        if c.field == "quantity" and c.old.number is not None and c.new.number is not None and c.new.number > c.old.number:
            text = "I'd rather not go above the amount we first talked about."
            self._say("say-quantity", "The amount went up", text, 60, f"{c.old.display} became {c.new.display}.")
            self._risk("quantity", "The amount was pushed up", 10)

    # --- output -----------------------------------------------------------------------

    def _expire(self) -> None:
        now = utc_now()
        for key, s in list(self._items.items()):
            if s.expires_at is not None and s.expires_at <= now:
                self._expired[key] = self._items.pop(key)
        self._publish()

    def _publish(self, force: bool = False) -> None:
        ranked = sorted(self._items.values(), key=lambda s: (-s.priority, s.checked_at or utc_now()))
        say = [s for s in ranked if s.kind == "say_this"]
        research = [s for s in ranked if s.kind == "research"]
        # Up to two "say this" lines first, then research as evidence; free slots go to whichever has more.
        visible = say[:MAX_SAY_THIS] + research[: MAX_VISIBLE - min(len(say), MAX_SAY_THIS)]
        visible += [s for s in say[MAX_SAY_THIS:] if len(visible) < MAX_VISIBLE and s not in visible][: MAX_VISIBLE - len(visible)]
        visible = sorted(visible, key=lambda s: (s.kind != "say_this", -s.priority))
        overflow = [s for s in ranked if s not in visible]
        earlier = list(self._expired.values()) + overflow
        state = (tuple(s.model_dump_json() for s in visible), tuple(s.id for s in earlier))
        if force or state != self._last:
            self._last = state
            self.bus.publish(SuggestionsUpdated(visible=visible, earlier=earlier))
        reasons = sorted(self._reasons.values(), key=lambda r: -r.points)
        score = min(100, sum(r.points for r in reasons))
        risk = (score, tuple(r.label for r in reasons))
        if self._assessed and (force or risk != self._last_risk):
            self._last_risk = risk
            self.bus.publish(RiskUpdated(score=score, level=level_for(score), reasons=reasons))
