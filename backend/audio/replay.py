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
from pipeline.events import (
    CallEnded,
    ClaimChecked,
    ClaimExtracted,
    Event,
    Offer,
    OfferChanged,
    OfferUpdated,
    ResearchReady,
    RiskUpdated,
    SpeakersUpdated,
    SuggestionsUpdated,
    TacticFlagged,
    TranscriberStatus,
    UtteranceFinal,
)
from pipeline.latency import LOG_PATH
from pipeline.llm import fast_llm
from pipeline.session import UI_EVENTS, CallSession
from pipeline.transcriber import DeepgramTranscriber
from detector.classifier import TacticClassifier
from memo.store import MemoStore
from providers.catalog import default_catalog
from providers.market import FinnhubProvider, FixtureProvider, RoutedMarketData

final_offer: list[Offer] = []


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
    elif isinstance(event, OfferChanged):
        c = event.change
        print(f"  · offer changed: {c.field} {c.old.display} -> {c.new.display}")
    elif isinstance(event, OfferUpdated):
        final_offer[:] = [event.offer]
    elif isinstance(event, ClaimExtracted):
        c = event.claim
        print(f"  · claim ({c.metric}): {c.text!r} value={c.claimed_value} {c.unit or ''} period={c.period}")
    elif isinstance(event, ClaimChecked):
        c = event.claim
        actual = f" data={c.actual_value:+g}" if c.actual_value is not None and c.metric != "price" else (f" market=${c.actual_value}" if c.actual_value is not None else "")
        print(f"  ✓ CHECKED {c.metric}: {c.status.upper()}{actual} ({c.note or ''}) [{c.source or 'no source'}] in {c.checked_in_ms} ms")
    elif isinstance(event, ResearchReady):
        i = event.item
        if i.status != "prefetching":
            print(f"  · research {i.status} [{i.wording}]: {i.title}: {i.summary}")
    elif isinstance(event, SuggestionsUpdated):
        top = [f"{s.priority}:{s.id}" for s in event.visible]
        if top != _last_top:
            _last_top[:] = top
            print(f"  · suggestions: {', '.join(top)}")
    elif isinstance(event, RiskUpdated):
        print(f"  · RISK {event.score} {event.level}: " + "; ".join(f"+{r.points} {r.label}" for r in event.reasons))
    elif isinstance(event, TacticFlagged):
        f = event.flag
        print(f"  ! TACTIC {f.tactic} ({f.severity}, {f.source}, p={f.score}): {f.quote[:70]!r}")
    elif isinstance(event, CallEnded):
        print(f"  · call ended ({event.reason})")


_last_top: list[str] = []


def print_offer(offer: Offer) -> None:
    print("\nFinal offer")
    for name in ("caller_name", "firm", "instrument", "price", "quantity", "total", "deadline", "payment", "fees"):
        term = getattr(offer, name)
        if term is not None:
            print(f"  {name:<12} {term.display}  ({'computed' if term.source == 'computed' else repr(term.said)})")


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
    settings = get_settings()
    session = CallSession(
        source,
        DeepgramTranscriber(settings.deepgram_api_key),
        print_event,
        replay_id=path.stem,
        llm=fast_llm(settings.gemini_api_key, settings.tenor_model_fast, settings.tenor_llm_timeout_s),
        market=RoutedMarketData(
            FixtureProvider(default_catalog()), FinnhubProvider(settings.finnhub_api_key, timeout_s=settings.finnhub_timeout_s)
        ),
        wording_timeout=settings.tenor_wording_timeout_s,
        classifier=TacticClassifier.load_default(),
        store=MemoStore(),
        memo_llm=fast_llm(settings.gemini_api_key, settings.tenor_model_memo, settings.tenor_memo_timeout_s),
        forward=(*UI_EVENTS, ClaimExtracted),
    )
    print(f"Replaying {path.name} ({source.duration_s:.1f} s), call {session.id}")
    await session.run()
    memo = await session.memo_task if session.memo_task else None
    if memo is not None:
        print(f"\nMemo [{memo.summary_wording}]: {memo.headline}\n  {memo.summary}")
        print(f"  saved: GET /api/calls/{memo.call_id}/memo")
    if final_offer:
        print_offer(final_offer[0])

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
