"""Replay a recorded call through the real pipeline, without the browser.

    uv run python -m audio.replay fixtures/calls/m1_hello.wav

Plays the file in real time (Deepgram's live API transcribes at about real-time
speed, so feeding it faster only stalls the end of the call). Prints the labeled
transcript, then a latency summary for this call from logs/latency.jsonl.
"""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from app.config import get_settings
from audio.sources import FileSource
from pipeline.events import CallEnded, Event, SpeakersUpdated, TranscriberStatus, UtteranceFinal
from pipeline.latency import LOG_PATH
from pipeline.session import CallSession
from pipeline.transcriber import DeepgramTranscriber


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


async def print_event(event: Event) -> None:
    if isinstance(event, UtteranceFinal):
        u = event.utterance
        who = "You" if u.speaker == "user" else "Caller"
        print(f"[{_clock(u.t_start)}] {who:<6} {u.text}")
    elif isinstance(event, SpeakersUpdated):
        print(f"  · You = speakers {event.user_indices} ({event.reason})")
    elif isinstance(event, TranscriberStatus):
        print(f"  · transcription {event.state}{': ' + event.detail if event.detail else ''}")
    elif isinstance(event, CallEnded):
        print(f"  · call ended ({event.reason})")


def latency_summary(call_id: str) -> dict[str, list[float]]:
    stages: dict[str, list[float]] = {}
    if not LOG_PATH.exists():
        return stages
    for line in LOG_PATH.read_text().splitlines():
        entry = json.loads(line)
        if entry.get("call_id") == call_id:
            stages.setdefault(entry["stage"], []).append(entry["ms"])
    return stages


async def main(path: Path) -> None:
    source = FileSource(path)
    session = CallSession(
        source,
        DeepgramTranscriber(get_settings().deepgram_api_key),
        print_event,
        replay_id=path.stem,
    )
    print(f"Replaying {path.name} ({source.duration_s:.1f} s), call {session.id}")
    await session.run()

    stages = latency_summary(session.id)
    if stages:
        print("\nLatency (ms)        n   median     p95")
        for stage, values in sorted(stages.items()):
            p95 = sorted(values)[max(0, round(0.95 * len(values)) - 1)]
            print(f"{stage:<16} {len(values):>4} {statistics.median(values):>8.0f} {p95:>7.0f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.wav))
