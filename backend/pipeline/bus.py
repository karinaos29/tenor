"""In-process async event bus, one per call.

Components never call each other: they publish events here and subscribe to the
types they need. Each subscriber has its own bounded queue, so a slow consumer
(e.g. the research agent) can never hold up a fast one (e.g. the transcript).

    bus = EventBus()
    sub = bus.subscribe(UtteranceFinal, SpeakersUpdated)
    bus.publish(event)            # never blocks
    async for event in sub: ...   # ends when sub.close() or bus.close()
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from pipeline.events import Event

log = logging.getLogger("tenor.bus")

_CLOSED = object()


class Subscription:
    def __init__(self, bus: "EventBus", types: tuple[type[Event], ...], maxsize: int) -> None:
        self._bus = bus
        self._types = types
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self.dropped = 0

    def wants(self, event: Event) -> bool:
        return not self._types or isinstance(event, self._types)

    def offer(self, event: object) -> None:
        if self._closed:
            return
        if self._queue.full():
            # Drop the oldest event rather than block the publisher.
            self._queue.get_nowait()
            self.dropped += 1
            log.warning("subscriber %s overflowed; dropped oldest event", self._names())
        self._queue.put_nowait(event)

    def close(self) -> None:
        if self._closed:
            return
        self._bus._remove(self)
        # The sentinel goes in even if the queue is full, so the reader always ends.
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(_CLOSED)
        self._closed = True

    def _names(self) -> str:
        return ",".join(t.__name__ for t in self._types) or "*"

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        item = await self._queue.get()
        if item is _CLOSED:
            raise StopAsyncIteration
        assert isinstance(item, Event)
        return item


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subs: list[Subscription] = []
        self._maxsize = maxsize

    def subscribe(self, *types: type[Event]) -> Subscription:
        """Subscribe to these event types (all events if none given)."""
        sub = Subscription(self, types, self._maxsize)
        self._subs.append(sub)
        return sub

    def publish(self, event: Event) -> None:
        for sub in list(self._subs):
            if sub.wants(event):
                sub.offer(event)

    def close(self) -> None:
        for sub in list(self._subs):
            sub.close()

    def _remove(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)
