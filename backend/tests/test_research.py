"""ResearchAgent: facts first, template summary, optional guarded LLM rewording."""

import asyncio

import pytest

from pipeline.bus import EventBus
from pipeline.events import EntitiesClosed, EntityDetected, ResearchClosed, ResearchReady
from pipeline.llm import HedgedLlm
from pipeline.research import ResearchAgent, number_guard, numbers_in
from providers.catalog import default_catalog
from providers.market import FixtureProvider, RoutedMarketData
from providers.register import FixtureRegister
from tests.m3_helpers import FakeMarket, latency_entries, make_entity

CATALOG = default_catalog()


def routed():
    return RoutedMarketData(FixtureProvider(CATALOG), None)


class FakeLlm:
    available = True

    def __init__(self, text=None, delay=0.0):
        self.text, self.delay, self.calls = text, delay, 0

    async def generate_text(self, *, system, prompt, stage, call_id=""):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.text


class FakeHedged(HedgedLlm):
    """A HedgedLlm whose answer is fixed; applies `accept` the way the real one does."""

    def __init__(self, text):
        super().__init__([])
        self.text, self.accept_seen = text, None

    @property
    def available(self):
        return True

    async def generate_text(self, *, system, prompt, stage, call_id="", accept=lambda _t: True):
        self.accept_seen = accept
        return self.text if accept(self.text) else None


def research(entities, *, market=None, llm=None, **kw):
    async def main():
        bus = EventBus()
        agent = ResearchAgent(bus, market or routed(), FixtureRegister(CATALOG), CATALOG, llm, **kw)
        spy = bus.subscribe(ResearchReady, ResearchClosed, EntitiesClosed)
        task = asyncio.create_task(agent.run())
        for e in entities:
            bus.publish(EntityDetected(entity=e))
        bus.publish(EntitiesClosed())
        await asyncio.wait_for(task, 10)
        spy.close()
        return [e async for e in spy]

    return asyncio.run(main())


def items(seen):
    return [e.item for e in seen if isinstance(e, ResearchReady)]


def last_by_id(seen):
    return {i.id: i for i in items(seen)}


KSTL = make_entity("ticker", "KSTL")
HC = make_entity("firm", "Hartwell & Crane", id="e2")


# --- prefetch then ready ------------------------------------------------------------


def test_prefetching_then_ready_with_stable_ids():
    seen = research([KSTL, HC])
    got = items(seen)
    assert [(i.id, i.status) for i in got if i.id == "r-ticker-kstl"] == [("r-ticker-kstl", "prefetching"), ("r-ticker-kstl", "ready")]
    assert [i.status for i in got if i.id == "r-firm-hartwell-crane"] == ["prefetching", "ready"]
    final = last_by_id(seen)
    t = final["r-ticker-kstl"]
    assert t.topic == "ticker" and t.wording == "template" and t.checked_at is not None
    assert "$0.38" in t.summary and "down 12.5%" in t.summary and "No news" in t.summary
    labels = {f.label: f.value for f in t.facts}
    assert labels["Price now"] == "$0.38" and labels["Last 13 weeks"] == "-12.5%"
    assert t.source == FixtureProvider.SOURCE
    assert items(seen)[0].summary == "" and items(seen)[0].facts == []


def test_firm_findings():
    final = last_by_id(research([HC, make_entity("firm", "Riverside Savings Bank", id="e3")]))
    hc, rs = final["r-firm-hartwell-crane"], final["r-firm-riverside-savings-bank"]
    assert hc.finding == "not_registered" and hc.status == "ready" and "not in the register" in hc.summary
    assert rs.finding == "registered" and rs.status == "ready" and "TEST-BANK-0147" in rs.summary


def test_unknown_firm_is_failed_without_finding():
    item = last_by_id(research([make_entity("firm", "Goldman Sachs")]))["r-firm-goldman-sachs"]
    assert item.status == "failed" and item.finding is None and "Couldn't check" in item.summary


def test_ticker_without_data_is_failed():
    item = last_by_id(research([make_entity("ticker", "VOO")]))["r-ticker-voo"]
    assert item.status == "failed" and "Couldn't find market data" in item.summary and item.facts == []


def test_provider_exception_gives_failed_item_not_crash():
    seen = research([KSTL], market=FakeMarket(boom=True))
    assert last_by_id(seen)["r-ticker-kstl"].status == "failed"
    assert seen[-1].type == "research.closed"


def test_unsure_tickers_and_other_kinds_are_skipped():
    seen = research([make_entity("ticker", "KSTX", confidence="unsure"), make_entity("price", "$0.42", id="e5")])
    assert items(seen) == []


def test_each_subject_researched_once():
    seen = research([KSTL, make_entity("ticker", "kstl", id="e9"), make_entity("ticker", "KSTL", id="e10", confidence="matched")])
    assert [i.status for i in items(seen)] == ["prefetching", "ready"]


def test_prefetch_latency_logged():
    research([KSTL, HC], call_id="c7")
    rows = latency_entries("research.prefetch")
    assert sorted(r["topic"] for r in rows) == ["firm", "ticker"] and rows[0]["call_id"] == "c7"


def test_research_closed_follows_entities_closed():
    kinds = [e.type for e in research([KSTL, HC])]
    assert kinds.index("entities.closed") < kinds.index("research.closed") == len(kinds) - 1


def test_slow_provider_is_cut_off_at_drain_timeout():
    seen = research([KSTL], market=FakeMarket(delay=5.0), drain_timeout=0.05)
    assert [i.status for i in items(seen)] == ["prefetching"]
    assert seen[-1].type == "research.closed"


# --- number guard -------------------------------------------------------------------

FACTS = "Price now: $0.38\nLast 13 weeks: -12.5%"
TEMPLATE = "Kestrel Motors (KSTL) trades at $0.38. Price change: last 13 weeks down 12.5%."


def test_numbers_in_normalizes_words_and_thousands():
    assert numbers_in("up forty percent and 1,200 shares") >= {"40", "1200"}
    assert numbers_in("no numbers here") == set()


def test_guard_all_good():
    assert number_guard("It trades at $0.38 and is down 12.5% over 13 weeks.", FACTS + TEMPLATE, TEMPLATE)


def test_guard_rejects_new_digits():
    assert not number_guard("It is down 99% over 13 weeks.", FACTS + TEMPLATE, TEMPLATE)


def test_guard_catches_numbers_written_as_words():
    assert not number_guard("It is up forty percent. Down 12.5% too.", FACTS + TEMPLATE, TEMPLATE)
    assert not number_guard("It trades at twenty dollars. 12.5% down.", FACTS + TEMPLATE, TEMPLATE)


def test_guard_rejects_dropped_template_percentage():
    assert not number_guard("It trades at $0.38 and has fallen lately.", FACTS + TEMPLATE, TEMPLATE)


def test_guard_without_numbers_passes_when_template_has_no_percent():
    assert number_guard("Nothing to see here.", "x", "")


# --- rewording ----------------------------------------------------------------------

GOOD = "Kestrel Motors costs $0.38 a share. It has fallen 12.5% in 13 weeks and 48% in 52 weeks."


def test_accepted_rewording_replaces_summary():
    llm = FakeLlm(GOOD)
    final = last_by_id(research([KSTL], llm=llm))["r-ticker-kstl"]
    assert final.summary == GOOD and final.wording == "gemini" and final.status == "ready" and llm.calls == 1
    assert latency_entries("research.wording")[-1]["ok"] is True


def test_reworded_item_publishes_after_template_ready():
    got = [(i.status, i.wording) for i in items(research([KSTL], llm=FakeLlm(GOOD)))]
    assert got == [("prefetching", "template"), ("ready", "template"), ("ready", "gemini")]


def test_text_with_new_number_is_rejected():
    final = last_by_id(research([KSTL], llm=FakeLlm("It fell 12.5% and may rise 300%.")))["r-ticker-kstl"]
    assert final.wording == "template" and "300" not in final.summary
    assert latency_entries("research.wording")[-1]["ok"] is False


def test_rewording_that_drops_the_percentage_is_rejected():
    final = last_by_id(research([KSTL], llm=FakeLlm("Kestrel Motors costs $0.38 a share.")))["r-ticker-kstl"]
    assert final.wording == "template"


def test_slow_llm_beyond_wording_timeout_keeps_template():
    seen = research([KSTL], llm=FakeLlm(GOOD, delay=2.0), wording_timeout=0.05)
    assert last_by_id(seen)["r-ticker-kstl"].wording == "template"
    assert seen[-1].type == "research.closed"


def test_llm_none_or_unavailable_is_template_only():
    for llm in (None, HedgedLlm([])):
        final = last_by_id(research([KSTL], llm=llm))["r-ticker-kstl"]
        assert final.wording == "template"
    assert latency_entries("research.wording") == []


def test_failed_item_is_never_reworded():
    llm = FakeLlm(GOOD)
    research([make_entity("ticker", "VOO")], llm=llm)
    assert llm.calls == 0


def test_hedged_llm_gets_an_accept_guard():
    llm = FakeHedged(GOOD)
    final = last_by_id(research([KSTL], llm=llm))["r-ticker-kstl"]
    assert llm.accept_seen is not None and final.wording == "gemini"
    assert not llm.accept_seen("It fell 12.5% and may rise 300%.")
    bad = FakeHedged("Up 77%.")
    assert last_by_id(research([KSTL], llm=bad))["r-ticker-kstl"].wording == "template"
