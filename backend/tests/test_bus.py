import asyncio

from pipeline.bus import EventBus
from pipeline.events import AudioLevel, CallStop, TranscriptClosed


def lvl(i: int) -> AudioLevel:
    return AudioLevel(t=i * 0.08, dbfs=-20.0)


async def collect(sub, n: int) -> list:
    return [await asyncio.wait_for(sub.__anext__(), 1) for _ in range(n)]


def test_fan_out_to_two_subscribers():
    async def main():
        bus = EventBus()
        a, b = bus.subscribe(), bus.subscribe()
        events = [lvl(0), lvl(1), TranscriptClosed()]
        for e in events:
            bus.publish(e)
        assert await collect(a, 3) == events
        assert await collect(b, 3) == events

    asyncio.run(main())


def test_type_filtering():
    async def main():
        bus = EventBus()
        levels = bus.subscribe(AudioLevel)
        both = bus.subscribe(AudioLevel, TranscriptClosed)
        bus.publish(CallStop())
        bus.publish(lvl(0))
        bus.publish(TranscriptClosed())
        got = await collect(levels, 1)
        assert [type(e) for e in got] == [AudioLevel]
        assert [type(e) for e in await collect(both, 2)] == [AudioLevel, TranscriptClosed]
        bus.close()
        assert [e async for e in levels] == []  # TranscriptClosed was never queued

    asyncio.run(main())


def test_publish_never_blocks_and_drops_oldest():
    async def main():
        bus = EventBus(maxsize=3)
        sub = bus.subscribe()
        for i in range(10):
            bus.publish(lvl(i))  # sync call, no awaiting: must not block
        assert sub.dropped == 7
        got = await collect(sub, 3)
        assert [round(e.t / 0.08) for e in got] == [7, 8, 9]

    asyncio.run(main())


def test_slow_subscriber_does_not_affect_others():
    async def main():
        bus = EventBus(maxsize=2)
        slow, fast = bus.subscribe(), bus.subscribe()
        for i in range(5):
            bus.publish(lvl(i))
            await collect(fast, 1)
        assert fast.dropped == 0
        assert slow.dropped == 3

    asyncio.run(main())


def test_sub_close_ends_iteration_and_unsubscribes():
    async def main():
        bus = EventBus()
        sub, other = bus.subscribe(), bus.subscribe()
        bus.publish(lvl(0))
        sub.close()
        sub.close()  # idempotent
        bus.publish(lvl(1))
        # Items queued before close are still ahead of the sentinel? Either way it must end.
        seen = [e async for e in sub]
        assert len(seen) <= 1
        assert len(await collect(other, 2)) == 2

    asyncio.run(main())


def test_bus_close_ends_all_readers_even_when_full():
    async def main():
        bus = EventBus(maxsize=2)
        subs = [bus.subscribe(), bus.subscribe(AudioLevel)]
        for i in range(5):
            bus.publish(lvl(i))
        bus.close()

        async def drain(s):
            return [e async for e in s]

        for s in subs:
            await asyncio.wait_for(drain(s), 1)

    asyncio.run(main())


def test_reader_blocked_in_async_for_ends_on_close():
    async def main():
        bus = EventBus()
        sub = bus.subscribe()

        async def reader():
            return [e async for e in sub]

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.01)
        bus.close()
        assert await asyncio.wait_for(task, 1) == []

    asyncio.run(main())
