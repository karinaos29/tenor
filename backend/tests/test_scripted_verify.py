"""The scripted calls through the whole text pipeline: extract -> offer -> check + research -> suggestions.

No audio, no LLM, no network: fixture market data (live=None) and the fixture register.
Ground truth: fixtures/calls/expected/<name>.json (checks, research, risk, first_say_this, no_check_status).
"""

import asyncio

import pytest

from pipeline.bus import EventBus
from pipeline.checker import ClaimChecker
from pipeline.events import (
    ClaimChecked,
    ResearchReady,
    RiskUpdated,
    SuggestionsUpdated,
    Utterance,
    UtterancesClosed,
    UtteranceFinal,
)
from pipeline.extractor import EntityExtractor
from pipeline.offer import OfferTracker
from pipeline.research import ResearchAgent
from pipeline.suggestions import SuggestionEngine
from providers.catalog import default_catalog
from providers.market import FixtureProvider, RoutedMarketData
from providers.register import FixtureRegister
from tests.test_scripted_calls import NAMES, expected, script_lines


def run_pipeline(name: str, *, pace: float | None = 0.005):
    async def main():
        catalog = default_catalog()
        bus = EventBus()
        market = RoutedMarketData(FixtureProvider(catalog), None)
        tasks = [
            EntityExtractor(bus, catalog, None).run(),
            OfferTracker(bus).run(),
            ClaimChecker(bus, market).run(),
            ResearchAgent(bus, market, FixtureRegister(catalog), catalog, None).run(),
            SuggestionEngine(bus).run(),
        ]
        spy = bus.subscribe(ClaimChecked, ResearchReady, SuggestionsUpdated, RiskUpdated)
        running = [asyncio.create_task(t) for t in tasks]
        await asyncio.sleep(0)
        for i, (speaker, text) in enumerate(script_lines(name)):
            u = Utterance(id=f"u{i}", speaker=speaker, speaker_index=0 if speaker == "user" else 1, text=text, t_start=float(i), t_end=i + 0.9, is_final=True)
            bus.publish(UtteranceFinal(utterance=u))
            if pace is not None:
                await asyncio.sleep(pace)  # speech takes time; None = the whole call arrives in one burst
        bus.publish(UtterancesClosed())
        await asyncio.wait_for(asyncio.gather(*running), 15)
        spy.close()
        return [e async for e in spy]

    return asyncio.run(main())


@pytest.fixture(scope="module", params=NAMES)
def verified(request):
    name = request.param
    events = run_pipeline(name)
    return name, expected(name), events


def checked(events):
    latest = {}
    for e in events:
        if isinstance(e, ClaimChecked):
            latest[e.claim.id] = e.claim
    return list(latest.values())


def check_matches(c, want):
    if c.metric != want["metric"] or c.status != want["status"]:
        return False
    if "claimed_value" in want and c.claimed_value != want["claimed_value"]:
        return False
    if "actual_value" in want and c.actual_value != want["actual_value"]:
        return False
    return "note" not in want or want["note"] in (c.note or "")


def test_every_expected_check_is_matched(verified):
    _, want, events = verified
    got = checked(events)
    for w in want["checks"]:
        assert any(check_matches(c, w) for c in got), (w, [(c.metric, c.status, c.claimed_value, c.actual_value, c.note) for c in got])


def test_forbidden_statuses_never_appear(verified):
    _, want, events = verified
    banned = set(want.get("no_check_status", []))
    bad = [(c.metric, c.status, c.text) for c in checked(events) if c.status in banned]
    assert not bad, bad


def test_every_check_has_a_final_verdict_and_check_time(verified):
    _, _, events = verified
    for c in checked(events):
        assert c.status != "checking" and c.checked_in_ms is not None


def test_expected_research(verified):
    _, want, events = verified
    final = {}
    for e in events:
        if isinstance(e, ResearchReady):
            final[e.item.id] = e.item
    for w in want["research"]:
        item = final[w["id"]]
        assert all(getattr(item, k) == v for k, v in w.items() if k != "id"), (w, item)


def test_final_risk(verified):
    _, want, events = verified
    risk = [e for e in events if isinstance(e, RiskUpdated)][-1]
    assert risk.level == want["risk"]["level"]
    assert risk.score >= want["risk"].get("min_score", 0)
    assert risk.score <= want["risk"].get("max_score", 100)


def test_first_say_this(verified):
    _, want, events = verified
    visible = [e for e in events if isinstance(e, SuggestionsUpdated)][-1].visible
    say = [s for s in visible if s.kind == "say_this"]
    if "first_say_this" in want:
        assert say and say[0].id.startswith(want["first_say_this"]), [s.id for s in visible]
    assert len(visible) <= 4


def test_scam_says_the_exact_price_sentence():
    events = run_pipeline("scam_kstl")
    visible = [e for e in events if isinstance(e, SuggestionsUpdated)][-1].visible
    assert "Over the last three months KSTL went down 12.5%" in visible[0].text


def test_honest_call_gets_no_say_this_pressure_lines():
    events = run_pipeline("honest_voo")
    last = [e for e in events if isinstance(e, SuggestionsUpdated)][-1]
    assert [s.id for s in last.visible + last.earlier if s.kind == "say_this"] == []
    voo = {e.item.id: e.item for e in events if isinstance(e, ResearchReady)}["r-ticker-voo"]
    assert voo.status == "failed"  # no live data in tests; "couldn't verify", not a guess


def test_price_check_survives_a_burst_of_utterances():
    got = checked(run_pipeline("scam_kstl", pace=None))
    assert any(c.metric == "price" and c.status == "false" for c in got)
