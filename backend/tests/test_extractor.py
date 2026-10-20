"""EntityExtractor through a real EventBus, with a scripted fake LLM."""

import asyncio

from pipeline.bus import EventBus
from pipeline.events import (
    ClaimExtracted,
    EntitiesClosed,
    EntityDetected,
    Utterance,
    UtterancesClosed,
    UtteranceFinal,
)
from pipeline.extractor import EntityExtractor, ExtractionResult, LlmClaim, LlmEntity
from providers.catalog import default_catalog

KNOWN_NAMES = "My name is Daniel Reeves, I'm calling from Hartwell and Crane."
DEAL = "They just signed a deal with a major carmaker."


class FakeLlm:
    available = True

    def __init__(self, result: ExtractionResult | None = None, delay: float = 0.0) -> None:
        self.result = result
        self.delay = delay
        self.calls: list[dict] = []

    async def generate(self, system, prompt, schema, stage, call_id):  # noqa: ANN001
        self.calls.append({"system": system, "prompt": prompt, "schema": schema, "stage": stage, "call_id": call_id})
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


def utt(i: int, speaker: str, text: str) -> UtteranceFinal:
    return UtteranceFinal(
        utterance=Utterance(
            id=f"u{i}", speaker=speaker, speaker_index=0 if speaker == "user" else 1,
            text=text, t_start=float(i), t_end=i + 0.9, is_final=True,
        )  # fmt: skip
    )


def run_lines(lines: list[tuple[str, str]], llm=None, **kw):
    """Feed (speaker, text) lines, close, and return (events, extractor)."""

    async def main():
        bus = EventBus()
        extractor = EntityExtractor(bus, default_catalog(), llm, **kw)
        sub = bus.subscribe()
        for i, (speaker, text) in enumerate(lines):
            bus.publish(utt(i, speaker, text))
        bus.publish(UtterancesClosed())
        await asyncio.wait_for(extractor.run(), 5)
        sub.close()
        return [e async for e in sub], extractor

    return asyncio.run(main())


def of(events, cls):
    return [e for e in events if isinstance(e, cls)]


def result(claims=(), entities=()):
    return ExtractionResult(claims=list(claims), entities=list(entities))


def llm_claim(text, metric="event", value=None, unit=None, period=None, subject=None):
    return LlmClaim(text=text, metric=metric, claimed_value=value, unit=unit, period=period, subject=subject)


# --- rules stage -----------------------------------------------------------------------------


def test_rules_entities_for_caller_and_user_with_speaker():
    events, _ = run_lines([("caller", "The shares are 42 cents each."), ("user", "Five thousand shares at 42 cents?")])
    ents = of(events, EntityDetected)
    by_speaker = {(e.entity.speaker, e.entity.kind) for e in ents}
    assert ("caller", "price") in by_speaker and ("caller", "ticker") not in by_speaker
    assert ("user", "price") in by_speaker and ("user", "quantity") in by_speaker
    assert {e.entity.utterance_id for e in ents if e.entity.speaker == "user"} == {"u1"}
    assert {e.entity.utterance_id for e in ents if e.entity.speaker == "caller"} == {"u0"}


def test_entities_have_unique_ids_and_utterance_time():
    events, _ = run_lines([("caller", "Start with 5,000 shares at 42 cents each.")])
    ents = [e.entity for e in of(events, EntityDetected)]
    assert len({e.id for e in ents}) == len(ents) >= 2
    assert all(e.t == 0.0 for e in ents)


def test_claims_only_for_caller_lines():
    text = "The stock is up 40% this quarter."
    events, _ = run_lines([("user", text), ("caller", text)])
    claims = of(events, ClaimExtracted)
    assert [c.claim.utterance_id for c in claims] == ["u1"]
    assert claims[0].claim.metric == "price_change"


def test_user_event_sentences_make_no_claims_and_no_llm_call():
    llm = FakeLlm(result())
    events, _ = run_lines([("user", DEAL)], llm)
    assert of(events, ClaimExtracted) == [] and llm.calls == []


def test_entities_closed_is_last():
    events, _ = run_lines([("caller", "Hello there.")])
    assert isinstance(events[-1], EntitiesClosed)
    assert len(of(events, EntitiesClosed)) == 1


# --- when the LLM is called -----------------------------------------------------------------------


def test_no_llm_call_without_event_cue_when_names_known():
    llm = FakeLlm(result())
    run_lines([("caller", KNOWN_NAMES), ("caller", "It is a nice day for it.")], llm)
    assert llm.calls == []


def test_llm_called_for_event_cue_lines():
    llm = FakeLlm(result())
    run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm)
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert DEAL in call["prompt"] and call["stage"] == "llm.extract" and call["schema"] is ExtractionResult


def test_llm_called_for_intro_lines_when_names_unknown():
    llm = FakeLlm(result())
    run_lines([("caller", "Good afternoon, is this Eszter?")], llm)
    assert len(llm.calls) == 1


def test_llm_never_called_for_user_lines():
    llm = FakeLlm(result())
    run_lines([("user", "Hello? Who is this?"), ("user", DEAL)], llm)
    assert llm.calls == []


def test_unavailable_llm_is_treated_as_none():
    llm = FakeLlm(result())
    llm.available = False
    events, ex = run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm)
    assert llm.calls == [] and ex.llm is None
    assert [c.claim.metric for c in of(events, ClaimExtracted)] == ["event"]


# --- filtering what the LLM says ---------------------------------------------------------------------


def test_llm_event_claim_is_published():
    llm = FakeLlm(result([llm_claim("signed a deal with a major carmaker", subject="KSTL")]))
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm)
    (c,) = [e.claim for e in of(events, ClaimExtracted)]
    assert c.metric == "event" and c.text == "signed a deal with a major carmaker" and c.subject == "KSTL"
    assert c.utterance_id == "u1" and c.status == "checking"


def test_llm_claim_not_quoted_from_utterance_is_dropped():
    llm = FakeLlm(result([llm_claim("they signed a billion dollar contract with Tesla")]))
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm)
    assert of(events, ClaimExtracted) == []  # and no fallback either: the LLM did answer


def test_llm_entity_of_kind_rules_already_found_is_dropped():
    text = "My name is Daniel Reeves. They signed a deal. I work for Orion Partners."
    llm = FakeLlm(result(entities=[LlmEntity(kind="person", text="Daniel Reeves"), LlmEntity(kind="firm", text="Orion Partners")]))
    events, _ = run_lines([("caller", text)], llm)
    ents = [e.entity for e in of(events, EntityDetected)]
    assert [e.value for e in ents if e.kind == "person"] == ["Daniel Reeves"]  # one, from rules
    assert [e.value for e in ents if e.kind == "firm"] == ["Orion Partners"]  # LLM filled the gap


def test_llm_entity_not_quoted_is_dropped():
    llm = FakeLlm(result(entities=[LlmEntity(kind="firm", text="Orion Partners")]))
    events, _ = run_lines([("caller", KNOWN_NAMES.replace("Hartwell and Crane", "somewhere") + " " + DEAL)], llm)
    assert not [e for e in of(events, EntityDetected) if e.entity.value == "Orion Partners"]


def test_llm_ticker_entity_unknown_to_catalog_is_unsure():
    text = "They signed a deal with Zorbex."
    llm = FakeLlm(result(entities=[LlmEntity(kind="ticker", text="Zorbex")]))
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", text)], llm)
    tick = [e.entity for e in of(events, EntityDetected) if e.entity.kind == "ticker"]
    assert len(tick) == 1 and tick[0].value == "ZORBEX" and tick[0].confidence == "unsure"


def test_llm_firm_alias_is_matched_to_canonical_name():
    text = "They signed a deal, says our partner Riverside Savings."
    llm = FakeLlm(result(entities=[LlmEntity(kind="firm", text="Riverside Savings")]))
    events, _ = run_lines([("caller", "My name is Daniel Reeves."), ("caller", text)], llm)
    # rules already match this firm by alias, so the LLM duplicate is dropped
    firms = [e.entity for e in of(events, EntityDetected) if e.entity.kind == "firm"]
    assert [(f.value, f.confidence) for f in firms] == [("Riverside Savings Bank", "matched")]


def test_llm_claim_with_metric_rules_already_produced_is_dropped():
    text = "The stock is up 40% this quarter. They signed a deal with a major carmaker."
    llm = FakeLlm(
        result(
            [
                llm_claim("The stock is up 40% this quarter", metric="price_change", value=40, unit="%"),
                llm_claim("signed a deal with a major carmaker"),
            ]
        )
    )
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", text)], llm)
    metrics = sorted(e.claim.metric for e in of(events, ClaimExtracted))
    assert metrics == ["event", "price_change"]  # one price_change (rules), one event (LLM)


# --- fallbacks ------------------------------------------------------------------------------------------


def test_llm_none_falls_back_to_rule_event_claims():
    llm = FakeLlm(None)
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm)
    claims = [e.claim for e in of(events, ClaimExtracted)]
    assert len(llm.calls) == 1
    assert [(c.metric, c.text) for c in claims] == [("event", DEAL)]


def test_no_llm_publishes_fallback_event_claims_immediately():
    async def main():
        bus = EventBus()
        extractor = EntityExtractor(bus, default_catalog(), None)
        sub = bus.subscribe(ClaimExtracted)
        bus.publish(utt(0, "caller", DEAL))
        task = asyncio.create_task(extractor.run())
        event = await asyncio.wait_for(sub.__anext__(), 2)  # before UtterancesClosed
        bus.publish(UtterancesClosed())
        await asyncio.wait_for(task, 2)
        return event

    event = asyncio.run(main())
    assert event.claim.metric == "event" and event.claim.text == DEAL


# --- draining -------------------------------------------------------------------------------------------


def test_close_waits_for_pending_llm_then_publishes_entities_closed():
    llm = FakeLlm(result([llm_claim("signed a deal with a major carmaker")]), delay=0.1)
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm)
    kinds = [type(e).__name__ for e in events]
    assert isinstance(events[-1], EntitiesClosed)
    assert "ClaimExtracted" in kinds  # the slow LLM claim arrived before the end marker


def test_drain_timeout_cancels_stuck_llm_and_still_closes():
    llm = FakeLlm(result(), delay=5)
    events, _ = run_lines([("caller", KNOWN_NAMES), ("caller", DEAL)], llm, drain_timeout=0.05)
    assert isinstance(events[-1], EntitiesClosed)


# --- subject tracking ------------------------------------------------------------------------------------


def test_claims_get_the_last_ticker_as_subject():
    lines = [
        ("caller", "It is a company called Kestrel Motors. The ticker is K S T L."),
        ("caller", "The stock is up 40% this quarter."),
        ("caller", "Our analysts say it's guaranteed to double by Christmas."),
    ]
    events, _ = run_lines(lines)
    claims = [e.claim for e in of(events, ClaimExtracted)]
    assert [c.subject for c in claims] == ["KSTL", "KSTL"]


def test_subject_follows_a_new_ticker():
    lines = [
        ("caller", "Take Kestrel Motors."),
        ("caller", "Or the ticker is V O O."),
        ("caller", "It is up 8% this year."),
    ]
    events, _ = run_lines(lines)
    assert [e.claim.subject for e in of(events, ClaimExtracted)] == ["VOO"]


def test_claim_before_any_ticker_has_no_subject():
    events, _ = run_lines([("caller", "It is up 8% this year.")])
    assert of(events, ClaimExtracted)[0].claim.subject is None


def test_llm_claim_subject_overrides_tracked_subject():
    llm = FakeLlm(result([llm_claim("signed a deal with a major carmaker", subject="ACME")]))
    events, _ = run_lines([("caller", KNOWN_NAMES + " The ticker is K S T L."), ("caller", DEAL)], llm)
    assert [e.claim.subject for e in of(events, ClaimExtracted)] == ["ACME"]
