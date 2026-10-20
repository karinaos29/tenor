"""SuggestionEngine: scored rules, ranking, expiry and the risk score (events published directly)."""

import asyncio

import pytest

from pipeline.bus import EventBus
from pipeline.events import (
    ChecksClosed,
    ClaimChecked,
    Offer,
    OfferChanged,
    OfferUpdated,
    ResearchClosed,
    ResearchItem,
    ResearchReady,
    RiskUpdated,
    SuggestionsUpdated,
    TermChange,
)
from pipeline.suggestions import SuggestionEngine, level_for
from tests.m3_helpers import make_claim, term


def drive(events, *, close=True, settle=0.0, **kw):
    """Publish `events`, optionally close both lanes, and return (suggestion updates, risk updates)."""

    async def main():
        bus = EventBus()
        engine = SuggestionEngine(bus, **kw)
        spy = bus.subscribe(SuggestionsUpdated, RiskUpdated)
        task = asyncio.create_task(engine.run())
        for e in events:
            bus.publish(e)
        if settle:
            await asyncio.sleep(settle)
        if close:
            bus.publish(ChecksClosed())
            bus.publish(ResearchClosed())
            await asyncio.wait_for(task, 5)
        else:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        spy.close()
        return [e async for e in spy]

    out = asyncio.run(main())
    return [e for e in out if isinstance(e, SuggestionsUpdated)], [e for e in out if isinstance(e, RiskUpdated)]


def false_change(id="c1"):
    return ClaimChecked(claim=make_claim(id=id, status="false", actual_value=-12.5, note="last 13 weeks", source="Test returns"))


def guarantee(id="g1"):
    return ClaimChecked(claim=make_claim(id=id, metric="guarantee", value=100, status="unverifiable"))


def firm_item(finding="not_registered", status="ready", subject="Hartwell & Crane"):
    slug = subject.lower().replace(" & ", "-").replace(" ", "-")
    return ResearchReady(item=ResearchItem(
        id=f"r-firm-{slug}", topic="firm", subject=subject, title=f"Who is {subject}?", status=status,
        summary=f"{subject} is not in the register.", source="Test register", finding=finding if status == "ready" else None,
    ))  # fmt: skip


def ticker_item(n=1, status="ready"):
    return ResearchReady(item=ResearchItem(id=f"r-ticker-t{n}", topic="ticker", subject=f"T{n}", title=f"How T{n} has done", status=status, summary="facts"))


def offer(deadline=None, payment=None):
    return OfferUpdated(offer=Offer(deadline=term(deadline) if deadline else None, payment=term(payment) if payment else None))


def final(updates):
    return updates[-1]


def ids(items):
    return [s.id for s in items]


# --- rules --------------------------------------------------------------------------


def test_false_price_change_is_top_priority_with_the_exact_sentence():
    updates, risks = drive([false_change()])
    s = final(updates).visible[0]
    assert s.id == "say-claim-c1" and s.priority == 100 and s.kind == "say_this"
    assert "Over the last three months KSTL went down 12.5%" in s.text
    assert s.text.startswith("That's not what I see.") and "in writing" in s.text
    assert "+40" in s.reason and "-12.5" in s.reason and s.source == "Test returns"
    assert final(risks).score == 30


def test_price_up_wording():
    c = ClaimChecked(claim=make_claim(id="u", value=-30, status="false", actual_value=8.0, note="this year so far"))
    assert "This year so far KSTL went up 8%" in final(drive([c])[0]).visible[0].text


def test_verified_claim_gives_no_suggestion_and_zero_risk():
    c = ClaimChecked(claim=make_claim(status="verified", actual_value=-12.5, value=-12.0))
    updates, risks = drive([c])
    assert final(updates).visible == []
    assert final(risks).score == 0 and final(risks).level == "low"


def test_not_registered_research_gives_register_line_and_risk_25():
    updates, risks = drive([firm_item()])
    f = final(updates)
    say = [s for s in f.visible if s.kind == "say_this"]
    assert ids(say) == ["say-register"] and say[0].priority == 90
    assert "Hartwell & Crane" in say[0].title
    assert final(risks).score == 25 and final(risks).level == "medium"
    assert "r-firm-hartwell-crane" in ids(f.visible)


def test_registered_firm_gives_no_register_line():
    updates, risks = drive([firm_item("registered", subject="Riverside Savings Bank")])
    assert [s for s in final(updates).visible if s.kind == "say_this"] == []
    assert final(risks).score == 0


def test_guarantee_priority_85():
    updates, risks = drive([guarantee()])
    s = final(updates).visible[0]
    assert s.id == "say-guarantee" and s.priority == 85 and "guarantee a share price" in s.text
    assert final(risks).score == 15


def test_same_day_deadline_priority_80_but_not_a_calendar_date():
    updates, risks = drive([offer(deadline="Today, 3:00 PM"), ClaimChecked(claim=make_claim(status="verified"))])
    s = final(updates).visible[0]
    assert s.id == "say-deadline" and s.priority == 80 and final(risks).score == 10
    for display in ("April 15", "Friday"):
        updates, risks = drive([offer(deadline=display), guarantee()])
        assert "say-deadline" not in ids(final(updates).visible)
        assert final(risks).score == 15  # only the guarantee


def test_quantity_increase_priority_60():
    ev = OfferChanged(change=TermChange(field="quantity", old=term("5,000 shares", 5000), new=term("10,000 shares", 10000)))
    updates, risks = drive([ev])
    s = final(updates).visible[0]
    assert s.id == "say-quantity" and s.priority == 60 and "5,000 shares became 10,000 shares" in s.reason
    assert risks == []  # an offer change alone is not an assessment yet


def test_quantity_decrease_or_other_field_is_ignored():
    down = OfferChanged(change=TermChange(field="quantity", old=term("10,000 shares", 10000), new=term("5,000 shares", 5000)))
    total = OfferChanged(change=TermChange(field="total", old=term("$2,100", 2100), new=term("$4,200", 4200)))
    updates, _ = drive([down, total])
    assert final(updates).visible == []


def test_risky_payment_only_when_firm_unregistered():
    updates, _ = drive([offer(payment="Bank transfer"), guarantee()])
    assert "say-payment" not in ids(final(updates).visible)
    updates, _ = drive([offer(payment="Bank transfer"), firm_item("registered", subject="Riverside Savings Bank")])
    assert "say-payment" not in ids(final(updates).visible)
    updates, _ = drive([offer(payment="Credit card"), firm_item()])
    assert "say-payment" not in ids(final(updates).visible + final(updates).earlier)


def test_risky_payment_fires_in_either_order():
    for events in ([offer(payment="Bank transfer"), firm_item()], [firm_item(), offer(payment="Bank transfer")]):
        updates, risks = drive(events)
        f = final(updates)
        assert "say-payment" in ids(f.visible + f.earlier)
        assert final(risks).score == 25 + 10


def test_price_mismatch_and_event_rules():
    price = ClaimChecked(claim=make_claim(id="p", metric="price", value=0.42, status="false", actual_value=0.38, note="10.5% above the market price", period=None))
    event = ClaimChecked(claim=make_claim(id="e", metric="event", value=None, status="not_found", period=None, note="No news"))
    updates, risks = drive([price, event])
    got = {s.id: s for s in final(updates).visible}
    assert got["say-price-KSTL"].priority == 70 and "$0.38, not $0.42" in got["say-price-KSTL"].text
    assert got["say-event-e"].priority == 75
    assert final(risks).score == 20


# --- ranking and visibility ---------------------------------------------------------


def test_visible_never_more_than_four_and_overflow_goes_to_earlier():
    events = [false_change("a"), false_change("b"), false_change("c"), guarantee(), offer(deadline="Today"), firm_item()]
    f = final(drive(events)[0])
    assert len(f.visible) <= 4
    assert len({s.id for s in f.visible + f.earlier}) == len(f.visible + f.earlier)
    assert {"say-claim-a", "say-claim-b", "say-claim-c", "say-guarantee", "say-deadline", "say-register", "r-firm-hartwell-crane"} <= set(ids(f.visible + f.earlier))
    assert len(ids(f.earlier)) >= 3


def test_with_research_at_most_two_say_this_visible_and_say_first():
    events = [false_change("a"), guarantee(), offer(deadline="Today, 3 PM"), ticker_item(1), ticker_item(2)]
    f = final(drive(events)[0])
    kinds = [s.kind for s in f.visible]
    assert kinds == ["say_this", "say_this", "research", "research"]
    assert ids(f.visible)[:2] == ["say-claim-a", "say-guarantee"]
    assert "say-deadline" in ids(f.earlier)


def test_without_research_free_slots_go_to_more_say_this():
    events = [false_change("a"), false_change("b"), false_change("c"), guarantee(), offer(deadline="Today")]
    f = final(drive(events)[0])
    assert len(f.visible) == 4 and all(s.kind == "say_this" for s in f.visible)
    assert len(f.earlier) == 1


def test_prefetching_research_is_shown_as_prefetching_then_replaced():
    updates, _ = drive([ticker_item(1, "prefetching"), ticker_item(1, "ready")])
    assert [s.status for s in updates[0].visible] == ["prefetching"]
    assert [s.status for s in final(updates).visible] == ["ready"]


def test_not_registered_research_ranks_above_other_research():
    f = final(drive([ticker_item(1), firm_item()])[0])
    research = [s for s in f.visible if s.kind == "research"]
    assert ids(research)[0] == "r-firm-hartwell-crane" and research[0].priority == 50


def test_say_this_expires_into_earlier():
    updates, _ = drive([guarantee()], close=False, settle=0.4, say_ttl_s=0.05, tick_s=0.02)
    f = final(updates)
    assert f.visible == [] and ids(f.earlier) == ["say-guarantee"]
    assert any(ids(u.visible) == ["say-guarantee"] for u in updates)  # it was visible first


def test_same_signal_again_revives_an_expired_line():
    async def main():
        bus = EventBus()
        engine = SuggestionEngine(bus, say_ttl_s=0.05, tick_s=0.02)
        spy = bus.subscribe(SuggestionsUpdated)
        task = asyncio.create_task(engine.run())
        bus.publish(guarantee())
        await asyncio.sleep(0.2)
        engine.say_ttl = engine.say_ttl * 1000
        bus.publish(guarantee())
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        spy.close()
        return [e async for e in spy]

    last = asyncio.run(main())[-1]
    assert ids(last.visible) == ["say-guarantee"] and ids(last.earlier) == []


# --- risk ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,level",
    [(0, "low"), (24, "low"), (25, "medium"), (49, "medium"), (50, "high"), (74, "high"), (75, "critical"), (100, "critical")],
)
def test_level_boundaries(score, level):
    assert level_for(score) == level


def test_risk_sum_is_capped_at_100():
    events = [false_change(str(i)) for i in range(5)] + [guarantee(), firm_item()]
    _, risks = drive(events)
    assert final(risks).score == 100 and final(risks).level == "critical"
    assert sum(r.points for r in final(risks).reasons) > 100


def test_risk_levels_climb_with_evidence():
    _, r = drive([firm_item()])
    assert (final(r).score, final(r).level) == (25, "medium")
    _, r = drive([firm_item(), false_change()])
    assert (final(r).score, final(r).level) == (55, "high")
    _, r = drive([firm_item(), false_change(), guarantee(), offer(deadline="Today")])
    assert (final(r).score, final(r).level) == (80, "critical")


def test_risk_reasons_sorted_by_points():
    _, r = drive([guarantee(), firm_item(), false_change()])
    pts = [x.points for x in final(r).reasons]
    assert pts == sorted(pts, reverse=True)


def test_risk_not_published_until_something_was_checked():
    # Only an offer term and a claim still being checked: nothing has been assessed.
    checking = ClaimChecked(claim=make_claim(status="checking"))
    _, risks = drive([offer(deadline="Today"), checking, ticker_item(1, "prefetching")])
    assert risks == []
    _, risks = drive([ticker_item(1, "failed")])
    assert risks == []


def test_risk_published_as_zero_low_after_first_assessed_result():
    _, risks = drive([ticker_item(1, "ready")])
    assert (final(risks).score, final(risks).level, final(risks).reasons) == (0, "low", [])
    verified = ClaimChecked(claim=make_claim(status="verified"))
    _, risks = drive([verified])
    assert (final(risks).score, final(risks).level) == (0, "low")


# --- lifecycle ----------------------------------------------------------------------


def test_run_waits_for_both_closed_events_then_publishes_final_state():
    async def main():
        bus = EventBus()
        task = asyncio.create_task(SuggestionEngine(bus).run())
        spy = bus.subscribe(SuggestionsUpdated)
        bus.publish(guarantee())
        bus.publish(ChecksClosed())
        await asyncio.sleep(0.1)
        assert not task.done()  # research lane still open
        n_before = spy._queue.qsize()
        bus.publish(ResearchClosed())
        await asyncio.wait_for(task, 5)
        assert spy._queue.qsize() > n_before  # the forced final publish
        spy.close()

    asyncio.run(main())


def test_final_publish_happens_even_with_no_events():
    updates, risks = drive([])
    assert updates and final(updates).visible == [] and final(updates).earlier == [] and risks == []
