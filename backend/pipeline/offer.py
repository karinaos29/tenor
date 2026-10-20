"""Offer tracker: the current offer as structured state, with change detection.

Only the caller's words fill the offer. A new value for a term that's already set
is a change ("10,000 shares, was 5,000"), kept in the history. The total is plain
arithmetic (price x quantity), never generated.

Consumes: EntityDetected, EntitiesClosed. Publishes: OfferUpdated, OfferChanged, OfferClosed.
"""

import time

from pipeline.bus import EventBus
from pipeline.events import (
    EntitiesClosed,
    Entity,
    EntityDetected,
    EntityKind,
    Offer,
    OfferChanged,
    OfferClosed,
    OfferField,
    OfferUpdated,
    Term,
    TermChange,
)
from pipeline.extractor import money
from pipeline.latency import record

FIELD_FOR_KIND: dict[EntityKind, OfferField] = {
    "ticker": "instrument",
    "price": "price",
    "quantity": "quantity",
    "deadline": "deadline",
    "payment": "payment",
    "fee": "fees",
    "person": "caller_name",
    "firm": "firm",
}


def term_from(e: Entity) -> Term:
    display = f"{e.value} · {e.detail}" if e.kind == "ticker" and e.detail else e.value
    return Term(display=display, number=e.number, said=e.text, utterance_id=e.utterance_id, t=e.t, confidence=e.confidence)


def same(a: Term, b: Term) -> bool:
    if a.number is not None and b.number is not None:
        return abs(a.number - b.number) < 1e-9
    return a.display.split(" · ")[0].lower() == b.display.split(" · ")[0].lower()


class OfferTracker:
    def __init__(self, bus: EventBus, *, call_id: str = "", source: str = "") -> None:
        self.bus = bus
        self.call_id = call_id
        self.source = source
        self.offer = Offer()
        self._sub = bus.subscribe(EntityDetected, EntitiesClosed)

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, EntityDetected):
                self.apply(event.entity)
            elif isinstance(event, EntitiesClosed):
                break
        self.bus.publish(OfferClosed())  # after every offer update, so the checker sees them all
        self._sub.close()

    def apply(self, e: Entity) -> None:
        field = FIELD_FOR_KIND.get(e.kind)
        if field is None or e.speaker != "caller":
            return
        started = time.perf_counter()
        new = term_from(e)
        old: Term | None = getattr(self.offer, field)
        changes: list[TermChange] = []
        if old is not None and same(old, new):
            if not (old.confidence == "unsure" and new.confidence != "unsure"):
                return  # repeated, nothing new
            # Same value heard more clearly: upgrade quietly, not a change.
        elif old is not None:
            changes.append(TermChange(field=field, old=old, new=new))
        updates: dict[str, object] = {field: new}

        if field in ("price", "quantity"):
            price = new if field == "price" else self.offer.price
            quantity = new if field == "quantity" else self.offer.quantity
            if price and quantity and price.number is not None and quantity.number is not None:
                amount = price.number * quantity.number
                unsure = "unsure" in (price.confidence, quantity.confidence)
                total = Term(display=money(amount), number=amount, said="", source="computed", confidence="unsure" if unsure else "heard")
                if self.offer.total is not None and not same(self.offer.total, total):
                    changes.append(TermChange(field="total", old=self.offer.total, new=total))
                updates["total"] = total

        self.offer = self.offer.model_copy(update={**updates, "history": [*self.offer.history, *changes]})
        for change in changes:
            self.bus.publish(OfferChanged(change=change))
        self.bus.publish(OfferUpdated(offer=self.offer))
        record("offer", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source)
