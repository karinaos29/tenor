"""Regressions from the live replay of the Silverline dialogue (2026-10-21), using
Deepgram's actual transcript."""

from pipeline.events import Entity
from pipeline.extractor import extract_rules
from pipeline.offer import OfferTracker
from pipeline.bus import EventBus
from providers.catalog import default_catalog

CAT = default_catalog()


def tickers(text):
    return {e.value: e.role for e in extract_rules(text, CAT).entities if e.kind == "ticker"}


def test_claim_subject_is_the_company_in_its_clause():
    text = "Apple shares are up 80% this year, and Bluewater is the next apple."
    claims = extract_rules(text, CAT).claims
    assert [(c.metric, c.claimed_value, c.subject) for c in claims] == [("price_change", 80.0, "AAPL")]


def test_comparison_mentions_are_not_on_offer():
    assert tickers("Apple shares are up 80% this year, and Bluewater is the next apple.") == {"AAPL": "mentioned", "BWLT": "mentioned"}
    assert tickers("Have you heard of Bluewater Lithium?") == {"BWLT": "offered"}
    assert tickers("We have a rare opportunity on a company called Kestrel Motors.") == {"KSTL": "offered"}


def test_real_word_after_ticker_cue_is_not_a_symbol():
    assert "BEING" not in tickers("The ticker is being double in lt.")


def _entity(kind, value, *, source="rules", role="offered"):
    return Entity(id=value, kind=kind, value=value, text=value, utterance_id="u1", speaker="caller", t=0.0, source=source, role=role)


def test_llm_value_never_overwrites_a_rule_value():
    tracker = OfferTracker(EventBus())
    tracker.apply(_entity("firm", "Silverline Capital Partners"))
    tracker.apply(_entity("firm", "Bluewater Lithium", source="llm"))
    assert tracker.offer.firm.display == "Silverline Capital Partners"
    tracker.apply(_entity("person", "Mark Collins", source="llm"))  # filling a gap is fine
    assert tracker.offer.caller_name.display == "Mark Collins"


def test_mentioned_ticker_does_not_change_the_instrument():
    tracker = OfferTracker(EventBus())
    tracker.apply(_entity("ticker", "BWLT"))
    tracker.apply(_entity("ticker", "AAPL", role="mentioned"))
    assert tracker.offer.instrument.display.startswith("BWLT")
    assert tracker.offer.history == []


def test_line_relabeled_to_caller_is_reprocessed():
    """The caller spoke first, so the first-turn rule labeled their intro as "You"; once
    loudness relabels it, the extractor must still pick up the caller's name."""
    import asyncio

    from pipeline.events import EntityDetected, SpeakersUpdated, Utterance, UtteranceFinal, UtterancesClosed
    from pipeline.extractor import EntityExtractor

    async def main():
        bus = EventBus()
        out = bus.subscribe(EntityDetected)
        task = asyncio.create_task(EntityExtractor(bus, CAT, None).run())
        intro = Utterance(id="u1", speaker="user", speaker_index=0, text="This is Mark Collins from Silverline Capital Partners.", t_start=0, t_end=3, is_final=True)
        bus.publish(UtteranceFinal(utterance=intro))
        await asyncio.sleep(0)
        bus.publish(SpeakersUpdated(user_indices=[1], reason="loudness", locked=False))
        bus.publish(UtterancesClosed())
        await task
        out.close()
        return [(e.entity.kind, e.entity.value, e.entity.speaker) async for e in out]

    found = asyncio.run(main())
    assert ("person", "Mark Collins", "caller") in found
    assert ("firm", "Silverline Capital Partners", "caller") in found
