"""SuggestionEngine with caller-identity gaps: pressure counts more when a fact backs it up."""

import asyncio

from pipeline.bus import EventBus
from pipeline.events import (
    IdentityClosed,
    IdentityGap,
    IdentityResolved,
    RiskUpdated,
    SuggestionsUpdated,
    TacticsClosed,
)
from pipeline.suggestions import SuggestionEngine
from tests.test_suggestions import firm_item
from tests.test_suggestions_tactics import all_items, flag

MISSING = IdentityGap(kind="missing", t=45)
EVADED = IdentityGap(kind="evaded", t=50, question="Which company are you calling from?")


def drive(events):
    async def main():
        bus = EventBus()
        engine = SuggestionEngine(bus, wait_for=("tactics", "identity"))
        spy = bus.subscribe(SuggestionsUpdated, RiskUpdated)
        task = asyncio.create_task(engine.run())
        for e in events:
            bus.publish(e)
        bus.publish(TacticsClosed())
        bus.publish(IdentityClosed())
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    out = asyncio.run(main())
    return [e for e in out if isinstance(e, SuggestionsUpdated)], [e for e in out if isinstance(e, RiskUpdated)]


def reasons(risk):
    return {r.label: r.points for r in risk.reasons}


def test_the_live_call_two_mild_tactics_and_no_firm_is_medium():
    _, risk = drive([flag("urgency", "mild", n=1), flag("guarantee", "mild", n=2), MISSING])
    assert reasons(risk[-1]) == {
        "The caller didn't say which firm they're from": 15,
        "Pressure from a caller who didn't say their firm (2 tactics)": 24,
        "Pressure: rushing you (mild)": 3,
        "Pressure: promises no risk (mild)": 3,
    }
    assert (risk[-1].score, risk[-1].level) == (45, "medium")


def test_the_same_call_with_a_dodged_question_is_high():
    _, risk = drive([flag("urgency", "mild", n=1), flag("guarantee", "mild", n=2), MISSING, EVADED])
    r = reasons(risk[-1])
    assert r["The caller didn't answer which firm they're from"] == 25
    assert r["Pressure from a caller who wouldn't say their firm (2 tactics)"] == 24
    assert "The caller didn't say which firm they're from" not in r
    assert (risk[-1].score, risk[-1].level) == (55, "high")


def test_tactics_without_an_identity_gap_add_no_bonus():
    _, risk = drive([flag("urgency", "mild", n=1), flag("guarantee", "mild", n=2)])
    assert risk[-1].score == 6


def test_repeated_tactic_counts_once_and_bonus_is_capped():
    _, risk = drive([flag("urgency", "mild", n=1), flag("urgency", "mild", n=2), MISSING])
    assert reasons(risk[-1])["Pressure from a caller who didn't say their firm (1 tactic)"] == 12
    many = [flag(t, "mild", n=i) for i, t in enumerate(["urgency", "scarcity", "secrecy", "authority", "skip_checks"])]
    _, risk = drive([*many, MISSING])
    assert reasons(risk[-1])["Pressure from a caller who didn't say their firm (5 tactics)"] == 36


def test_bonus_follows_tactics_that_arrive_after_the_gap():
    _, risk = drive([MISSING, flag("secrecy", "mild", n=1), flag("scarcity", "mild", n=2)])
    assert reasons(risk[-1])["Pressure from a caller who didn't say their firm (2 tactics)"] == 24


def test_gap_alone_makes_risk_visible_with_a_say_this_line():
    sugg, risk = drive([MISSING])
    assert (risk[-1].score, risk[-1].level) == (15, "low")
    (item,) = [s for s in all_items(sugg[-1]) if s.id == "say-identity"]
    assert item.kind == "say_this" and "Which company are you calling from?" in item.text


def test_named_firm_withdraws_the_missing_reasons():
    sugg, risk = drive([flag("urgency", "mild", n=1), MISSING, IdentityResolved(firm="Northgate Wealth")])
    assert reasons(risk[-1]) == {"Pressure: rushing you (mild)": 3}
    assert not [s for s in all_items(sugg[-1]) if s.id == "say-identity"]


def test_evaded_is_not_withdrawn_when_a_firm_is_named_later():
    _, risk = drive([flag("urgency", "mild", n=1), EVADED, IdentityResolved(firm="Northgate Wealth")])
    assert reasons(risk[-1])["The caller didn't answer which firm they're from"] == 25


def test_unregistered_firm_backs_up_the_tactics():
    _, risk = drive([flag("urgency", "mild", n=1), flag("secrecy", "strong", n=2), firm_item()])
    assert reasons(risk[-1])["Pressure from a firm that isn't registered (2 tactics)"] == 24
