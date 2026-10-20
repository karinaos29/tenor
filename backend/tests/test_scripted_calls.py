"""The scripted calls, as text, through extractor + offer tracker (rules only, no LLM, no audio).

Ground truth lives in fixtures/calls/expected/<name>.json.
"""

import asyncio
import json
from pathlib import Path

import pytest

from pipeline.bus import EventBus
from pipeline.events import ClaimExtracted, Offer, OfferChanged, OfferUpdated, Utterance, UtterancesClosed, UtteranceFinal
from pipeline.extractor import EntityExtractor
from pipeline.offer import OfferTracker
from providers.catalog import default_catalog

CALLS = Path(__file__).resolve().parents[1] / "fixtures" / "calls"
NAMES = ["scam_kstl", "honest_voo"]


def script_lines(name: str) -> list[tuple[str, str]]:
    out = []
    for raw in (CALLS / "scripts" / f"{name}.txt").read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        who, _, text = raw.partition(":")
        out.append(("caller" if who.strip() == "CALLER" else "user", text.strip()))
    return out


def run_script(name: str):
    async def main():
        bus = EventBus()
        extractor = asyncio.create_task(EntityExtractor(bus, default_catalog(), None).run())
        tracker = OfferTracker(bus)
        tracker_task = asyncio.create_task(tracker.run())
        sub = bus.subscribe(ClaimExtracted, OfferChanged, OfferUpdated)
        await asyncio.sleep(0)
        for i, (speaker, text) in enumerate(script_lines(name)):
            u = Utterance(
                id=f"u{i}", speaker=speaker, speaker_index=0 if speaker == "user" else 1,
                text=text, t_start=float(i), t_end=i + 0.9, is_final=True,
            )  # fmt: skip
            bus.publish(UtteranceFinal(utterance=u))
        bus.publish(UtterancesClosed())
        await asyncio.wait_for(asyncio.gather(extractor, tracker_task), 5)
        sub.close()
        events = [e async for e in sub]
        return tracker.offer, [e.claim for e in events if isinstance(e, ClaimExtracted)], events

    return asyncio.run(main())


def displays(offer: Offer) -> dict[str, str | None]:
    fields = ["caller_name", "firm", "instrument", "price", "quantity", "total", "deadline", "payment", "fees"]
    return {f: (getattr(offer, f).display if getattr(offer, f) else None) for f in fields}


def expected(name: str) -> dict:
    return json.loads((CALLS / "expected" / f"{name}.json").read_text())


@pytest.mark.parametrize("name", NAMES)
def test_final_offer_matches_expected(name):
    offer, _, _ = run_script(name)
    assert displays(offer) == expected(name)["offer"]


@pytest.mark.parametrize("name", NAMES)
def test_history_matches_expected_in_order(name):
    offer, _, events = run_script(name)
    got = [(c.field, c.old.display, c.new.display) for c in offer.history]
    want = [(c["field"], c["old"], c["new"]) for c in expected(name)["changes"]]
    assert got == want
    assert [e.change for e in events if isinstance(e, OfferChanged)] == offer.history


def claim_matches(claim, want: dict) -> bool:
    for key in ("metric", "claimed_value", "unit", "period", "subject"):
        if key in want and getattr(claim, key) != want[key]:
            return False
    return want.get("text_contains", "") in claim.text


@pytest.mark.parametrize("name", NAMES)
def test_every_expected_claim_is_published(name):
    _, claims, _ = run_script(name)
    for want in expected(name)["claims"]:
        assert any(claim_matches(c, want) for c in claims), (want, [(c.metric, c.claimed_value, c.period, c.subject, c.text) for c in claims])


def test_honest_call_has_no_guarantee_or_price_change_claims():
    _, claims, _ = run_script("honest_voo")
    assert not [c for c in claims if c.metric in ("guarantee", "price_change")], [(c.metric, c.text) for c in claims]


def test_scam_claims_only_come_from_caller_lines():
    _, claims, _ = run_script("scam_kstl")
    lines = dict(enumerate(script_lines("scam_kstl")))
    assert claims and all(lines[int(c.utterance_id[1:])][0] == "caller" for c in claims)

