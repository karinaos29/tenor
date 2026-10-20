"""Per-stage latency log. Every pipeline stage records how long it took.

Lines are appended as JSON to `logs/latency.jsonl`; the evaluation screen (M4)
reads this file. Usage:

    with timed("extract"):
        ...

    record("health.rtt", 12.3, source="client")
"""

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pipeline.events import utc_now

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "latency.jsonl"

log = logging.getLogger("tenor.latency")


def record(stage: str, ms: float, **extra: object) -> None:
    entry = {"ts": utc_now().isoformat(), "stage": stage, "ms": round(ms, 2), **extra}
    log.info("%s %.1f ms", stage, ms)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        # Latency logging must never break the call pipeline.
        log.warning("could not write latency log to %s", LOG_PATH)


@contextmanager
def timed(stage: str, **extra: object) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        record(stage, (time.perf_counter() - start) * 1000, **extra)
