"""SuggestionEngine with pressure-tactic flags."""

import asyncio

import pytest

from detector.taxonomy import BY_ID, TACTIC_IDS
from pipeline.bus import EventBus
from pipeline.events import (
    ChecksClosed,
    ClaimChecked,
    Offer,
    OfferUpdated,
    ResearchClosed,
    RiskUpdated,
    SuggestionsUpdated,
    TacticFlag,
    TacticFlagged,
    TacticsClosed,
)
from pipeline.suggestions import SuggestionEngine, level_for
from tests.m3_helpers import make_claim, term


def flag(tactic, severity="strong", n=1, quote="the caller's words"):
    return TacticFlagged(flag=TacticFlag(
        id=f"t{n}", tactic=tactic, label=BY_ID[tactic].label, quote=quote, severity=severity,
        utterance_id="u1", score=1.0, source="rule",
    ))  # fmt: skip


def drive(events, *, wait_for=("tactics",), close=("tactics",)):
    async def main():
        bus = EventBus()
        engine = SuggestionEngine(bus, wait_for=wait_for)
        spy = bus.subscribe(SuggestionsUpdated, RiskUpdated)
        task = asyncio.create_task(engine.run())
        for e in events:
            bus.publish(e)
        for c in close:
            bus.publish({"tactics": TacticsClosed, "checks": ChecksClosed, "research": ResearchClosed}[c]())
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    out = asyncio.run(main())
    return [e for e in out if isinstance(e, SuggestionsUpdated)], [e for e in out if isinstance(e, RiskUpdated)]


def all_items(update):
    return update.visible + update.earlier


@pytest.mark.parametrize("tactic", [t for t in TACTIC_IDS if t not in ("urgency", "guarantee")])
def test_say_this_comes_from_taxonomy(tactic):
    sugg, _ = drive([flag(tactic)])
    (item,) = [s for s in all_items(sugg[-1]) if s.id == f"say-tactic-{tactic}"]
    assert item.kind == "say_this" and item.text == BY_ID[tactic].say_this
    assert item.priority == BY_ID[tactic].priority and item.title == BY_ID[tactic].label
    assert "the caller's words" in item.reason


@pytest.mark.parametrize("tactic,key", [("urgency", "say-deadline"), ("guarantee", "say-guarantee")])
def test_urgency_and_guarantee_reuse_existing_keys(tactic, key):
    sugg, _ = drive([flag(tactic)])
    ids = [s.id for s in all_items(sugg[-1])]
    assert key in ids and f"say-tactic-{tactic}" not in ids


def test_deadline_offer_and_urgency_flag_make_one_suggestion_and_one_reason():
    events = [OfferUpdated(offer=Offer(deadline=term("today at 5 pm"))), flag("urgency")]
    sugg, risk = drive(events)
    assert [s.id for s in all_items(sugg[-1])].count("say-deadline") == 1
    assert len(risk[-1].reasons) == 1
    assert risk[-1].score == 15  # the strong flag upgrades the 10-point deadline reason


def test_urgency_flag_before_deadline_offer_is_not_downgraded():
    events = [flag("urgency"), OfferUpdated(offer=Offer(deadline=term("today at 5 pm")))]
    _, risk = drive(events)
    assert len(risk[-1].reasons) == 1 and risk[-1].score == 15


def test_guarantee_claim_and_flag_count_once():
    events = [ClaimChecked(claim=make_claim(metric="guarantee", value=100, status="unverifiable")), flag("guarantee")]
    _, risk = drive(events)
    assert len(risk[-1].reasons) == 1 and risk[-1].score == 15


def test_risk_points_strong_and_mild():
    assert drive([flag("secrecy", "strong")])[1][-1].score == 15
    assert drive([flag("secrecy", "mild")])[1][-1].score == 3


def test_later_strong_upgrades_mild_and_never_downgrades():
    _, up = drive([flag("secrecy", "mild", 1), flag("secrecy", "strong", 2)])
    assert up[-1].score == 15 and len(up[-1].reasons) == 1 and "(strong)" in up[-1].reasons[0].label
    _, down = drive([flag("secrecy", "strong", 1), flag("secrecy", "mild", 2)])
    assert down[-1].score == 15 and "(strong)" in down[-1].reasons[0].label


def test_eight_mild_flags_stay_low():
    _, risk = drive([flag(t, "mild", i) for i, t in enumerate(TACTIC_IDS)])
    assert risk[-1].score == 24 and risk[-1].level == "low" == level_for(24)


def test_strong_flags_add_up():
    _, risk = drive([flag("secrecy"), flag("scarcity", n=2)])
    assert risk[-1].score == 30 and risk[-1].level == "medium"


def test_flag_alone_makes_risk_visible():
    _, risk = drive([flag("authority", "mild")])
    assert risk and risk[-1].score == 3


def test_wait_for_tactics_keeps_running_until_tactics_closed():
    async def main():
        bus = EventBus()
        engine = SuggestionEngine(bus, wait_for=("checks", "research", "tactics"), tick_s=0.05)
        task = asyncio.create_task(engine.run())
        bus.publish(ChecksClosed())
        bus.publish(ResearchClosed())
        await asyncio.sleep(0.3)
        still_running = not task.done()
        bus.publish(TacticsClosed())
        await asyncio.wait_for(task, 5)
        return still_running

    assert asyncio.run(main()) is True


def test_default_wait_for_does_not_need_tactics():
    async def main():
        bus = EventBus()
        task = asyncio.create_task(SuggestionEngine(bus, tick_s=0.05).run())
        bus.publish(ChecksClosed())
        bus.publish(ResearchClosed())
        await asyncio.wait_for(task, 5)

    asyncio.run(main())
