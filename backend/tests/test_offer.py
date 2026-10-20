"""OfferTracker: the offer as state, with change history."""

import asyncio

from pipeline.bus import EventBus
from pipeline.events import EntitiesClosed, Entity, EntityDetected, OfferChanged, OfferUpdated
from pipeline.offer import OfferTracker


def ent(kind, value, *, number=None, detail=None, speaker="caller", confidence="heard", text=None, i=[0]):  # noqa: B006
    i[0] += 1
    return Entity(
        id=f"e{i[0]}", kind=kind, value=value, text=text or value, number=number, detail=detail,
        utterance_id=f"u{i[0]}", speaker=speaker, t=float(i[0]), confidence=confidence,
    )  # fmt: skip


def price(n, **kw):
    return ent("price", f"${n:.2f} a share", number=n, **kw)


def qty(n, **kw):
    return ent("quantity", f"{n:,} shares", number=float(n), **kw)


def setup():
    bus = EventBus()
    tracker = OfferTracker(bus)
    sub = bus.subscribe(OfferUpdated, OfferChanged)
    return bus, tracker, sub


def drain(sub):
    sub.close()

    async def collect():
        return [e async for e in sub]

    return asyncio.run(collect())


def test_caller_entities_fill_fields():
    bus, t, sub = setup()
    t.apply(ent("person", "Daniel Reeves"))
    t.apply(ent("firm", "Hartwell & Crane", confidence="matched"))
    t.apply(ent("ticker", "KSTL", detail="Kestrel Motors", confidence="matched"))
    t.apply(price(0.42))
    t.apply(qty(5000))
    t.apply(ent("deadline", "Today, 3:00 PM"))
    t.apply(ent("payment", "Bank transfer"))
    t.apply(ent("fee", "0.25% a year", number=0.25))
    o = t.offer
    assert o.caller_name.display == "Daniel Reeves"
    assert o.firm.display == "Hartwell & Crane" and o.firm.confidence == "matched"
    assert o.instrument.display == "KSTL · Kestrel Motors"
    assert o.price.display == "$0.42 a share" and o.price.number == 0.42
    assert o.quantity.display == "5,000 shares"
    assert o.deadline.display == "Today, 3:00 PM" and o.payment.display == "Bank transfer"
    assert o.fees.display == "0.25% a year"
    assert o.history == []
    assert o.total.display == "$2,100" and o.total.source == "computed" and o.total.number == 2100
    assert o.total.said == "" and o.total.confidence == "heard"
    assert len([e for e in drain(sub) if isinstance(e, OfferChanged)]) == 0


def test_term_keeps_provenance():
    _, t, _ = setup()
    e = ent("quantity", "5,000 shares", number=5000, text="five thousand shares")
    t.apply(e)
    q = t.offer.quantity
    assert q.said == "five thousand shares" and q.utterance_id == e.utterance_id and q.t == e.t


def test_user_entities_are_ignored():
    bus, t, sub = setup()
    t.apply(qty(5000, speaker="user"))
    t.apply(price(0.42, speaker="user"))
    assert t.offer.quantity is None and t.offer.price is None and t.offer.total is None
    assert drain(sub) == []


def test_percent_entities_are_ignored():
    bus, t, sub = setup()
    t.apply(ent("percent", "40%", number=40))
    assert t.offer == type(t.offer)()
    assert drain(sub) == []


def test_same_value_repeated_publishes_nothing_new():
    bus, t, sub = setup()
    t.apply(qty(5000))
    t.apply(qty(5000))
    t.apply(ent("deadline", "Today, 3:00 PM"))
    t.apply(ent("deadline", "today, 3:00 pm"))
    events = drain(sub)
    assert len([e for e in events if isinstance(e, OfferUpdated)]) == 2
    assert not [e for e in events if isinstance(e, OfferChanged)]
    assert t.offer.history == []


def test_different_value_records_change_and_publishes_changed():
    bus, t, sub = setup()
    t.apply(qty(5000))
    t.apply(qty(10000))
    assert t.offer.quantity.display == "10,000 shares"
    (change,) = t.offer.history
    assert change.field == "quantity" and change.old.display == "5,000 shares" and change.new.display == "10,000 shares"
    events = drain(sub)
    changed = [e for e in events if isinstance(e, OfferChanged)]
    assert [c.change for c in changed] == [change]
    # the changed event comes before the matching offer.updated
    assert isinstance(events[-1], OfferUpdated) and events[-1].offer.history == [change]


def test_non_numeric_change_compares_display():
    _, t, _ = setup()
    t.apply(ent("payment", "Bank transfer"))
    t.apply(ent("payment", "Gift cards"))
    assert [(c.field, c.old.display, c.new.display) for c in t.offer.history] == [("payment", "Bank transfer", "Gift cards")]


def test_total_is_price_times_quantity_in_either_order():
    _, t, _ = setup()
    t.apply(qty(5000))
    assert t.offer.total is None
    t.apply(price(0.42))
    assert t.offer.total.display == "$2,100" and t.offer.total.number == 2100

    _, t2, _ = setup()
    t2.apply(price(0.42))
    assert t2.offer.total is None
    t2.apply(qty(10000))
    assert t2.offer.total.display == "$4,200"


def test_total_recomputed_on_change_with_its_own_change():
    bus, t, sub = setup()
    t.apply(price(0.42))
    t.apply(qty(5000))
    t.apply(qty(10000))
    assert [(c.field, c.old.display, c.new.display) for c in t.offer.history] == [
        ("quantity", "5,000 shares", "10,000 shares"),
        ("total", "$2,100", "$4,200"),
    ]
    assert t.offer.total.display == "$4,200"
    changed = [e.change.field for e in drain(sub) if isinstance(e, OfferChanged)]
    assert changed == ["quantity", "total"]


def test_price_change_also_recomputes_total():
    _, t, _ = setup()
    t.apply(price(0.42))
    t.apply(qty(1000))
    t.apply(price(0.50))
    assert [c.field for c in t.offer.history] == ["price", "total"]
    assert t.offer.total.display == "$500"


def test_unsure_upgrades_quietly_to_matched_for_same_value():
    bus, t, sub = setup()
    t.apply(ent("ticker", "KSTL", confidence="unsure"))
    assert t.offer.instrument.confidence == "unsure"
    t.apply(ent("ticker", "KSTL", detail="Kestrel Motors", confidence="matched"))
    assert t.offer.instrument.confidence == "matched" and t.offer.instrument.display == "KSTL · Kestrel Motors"
    assert t.offer.history == []
    events = drain(sub)
    assert not [e for e in events if isinstance(e, OfferChanged)]
    assert len([e for e in events if isinstance(e, OfferUpdated)]) == 2


def test_matched_is_not_downgraded_by_unsure_repeat():
    _, t, _ = setup()
    t.apply(ent("ticker", "KSTL", detail="Kestrel Motors", confidence="matched"))
    before = t.offer
    t.apply(ent("ticker", "KSTL", confidence="unsure"))
    assert t.offer is before


def test_total_is_unsure_when_an_input_is_unsure():
    _, t, _ = setup()
    t.apply(price(0.42, confidence="unsure"))
    t.apply(qty(1000))
    assert t.offer.total.confidence == "unsure"


def test_run_stops_on_entities_closed():
    async def main():
        bus = EventBus()
        t = OfferTracker(bus)
        bus.publish(EntityDetected(entity=qty(5000)))
        bus.publish(EntityDetected(entity=qty(10000)))
        bus.publish(EntitiesClosed())
        bus.publish(EntityDetected(entity=qty(1)))  # after the close marker: not consumed
        await asyncio.wait_for(t.run(), 2)
        return t.offer

    offer = asyncio.run(main())
    assert offer.quantity.display == "10,000 shares" and len(offer.history) == 1
