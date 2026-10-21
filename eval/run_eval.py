"""Evaluate Tenor on the synthetic test set. Run from backend/:

    uv run python ../eval/run_eval.py               # text mode: fast, deterministic
    uv run python ../eval/run_eval.py --audio       # + real-time replays through Deepgram (latency)
    uv run python ../eval/run_eval.py --live-data   # + live Finnhub for real tickers

1. Utterance level, on eval/data/test.jsonl (written by a different model than the
   training set): rules only, classifier only, Tenor's detector (classifier OR rules),
   and a Gemini zero-shot baseline. Per-tactic precision / recall / F1, micro averages,
   "any tactic" detection, latency per line.
2. Call level, every scripted test call through the full pipeline (text mode: the
   script's lines as utterances): risk vs. expected band, false claims caught, tactic
   precision / recall per caller line, most suggestions visible at once.
3. --audio: the same calls as audio, in real time through Deepgram, 4 at a time:
   claim spoken -> verdict, and latency per stage, read back from the latency log.

Results: eval/results/eval.sqlite (every run) and eval/results/latest.json (the
evaluation screen and README read this one).
"""

import argparse
import asyncio
import json
import sqlite3
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from detector.classifier import TacticClassifier  # noqa: E402
from detector.rules import rule_tactics  # noqa: E402
from detector.taxonomy import BY_ID, TACTIC_IDS, labeling_guide  # noqa: E402
from pipeline.bus import EventBus  # noqa: E402
from pipeline.checker import ClaimChecker  # noqa: E402
from pipeline.events import (  # noqa: E402
    CallResult,
    ClaimChecked,
    DetectorScores,
    EvalReport,
    MetricRow,
    RiskUpdated,
    StageLatency,
    SuggestionsUpdated,
    TacticFlagged,
    Target,
    Utterance,
    UtteranceFinal,
    UtterancesClosed,
    utc_now,
)
from pipeline.extractor import EntityExtractor  # noqa: E402
from pipeline.latency import LOG_PATH  # noqa: E402
from pipeline.llm import fast_llm  # noqa: E402
from pipeline.offer import OfferTracker  # noqa: E402
from pipeline.research import ResearchAgent  # noqa: E402
from pipeline.suggestions import SuggestionEngine  # noqa: E402
from pipeline.tactics import PressureDetector, sentences  # noqa: E402
from providers.catalog import Catalog  # noqa: E402
from providers.market import FinnhubProvider, FixtureProvider, RoutedMarketData  # noqa: E402
from providers.register import FixtureRegister  # noqa: E402

DATA = ROOT / "eval" / "data"
RESULTS = ROOT / "eval" / "results"
CALLS = ROOT / "backend" / "fixtures" / "calls"
LEVELS = ["low", "medium", "high", "critical"]
DATA_NOTE = (
    "Synthetic benchmark. Training lines were written by Claude Sonnet; the held-out test lines and 9 of the 12 "
    "test calls by Claude Haiku from a separate brief, without access to the training set; 3 calls by Claude Opus. "
    "All calls are scripted and voiced by text-to-speech, not real phone calls. One round of feedback: after the "
    "first run, 130 training lines were added for the two kinds of honest speech the classifier over-flagged (short "
    "small talk, same-topic opposites); test lines were not changed, and thresholds are set on training data only."
)


# --- metrics ---------------------------------------------------------------------------


def scores(truth: list[set[str]], pred: list[set[str]], tactic: str | None) -> tuple[float, float, float, int]:
    """Precision, recall, F1, support. tactic=None scores 'any tactic' (binary)."""
    if tactic is None:
        t = [bool(x) for x in truth]
        p = [bool(x) for x in pred]
    else:
        t = [tactic in x for x in truth]
        p = [tactic in x for x in pred]
    tp = sum(a and b for a, b in zip(t, p, strict=True))
    fp = sum(b and not a for a, b in zip(t, p, strict=True))
    fn = sum(a and not b for a, b in zip(t, p, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 3), round(recall, 3), round(f1, 3), sum(t)


def micro(truth: list[set[str]], pred: list[set[str]]) -> tuple[float, float, float, int]:
    tp = sum(len(t & p) for t, p in zip(truth, pred, strict=True))
    fp = sum(len(p - t) for t, p in zip(truth, pred, strict=True))
    fn = sum(len(t - p) for t, p in zip(truth, pred, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 3), round(recall, 3), round(f1, 3), sum(len(t) for t in truth)


def detector_scores(name: str, truth: list[set[str]], pred: list[set[str]], latency_ms: float, note: str = "") -> DetectorScores:
    rows = []
    for tactic in TACTIC_IDS:
        p, r, f, n = scores(truth, pred, tactic)
        rows.append(MetricRow(tactic=tactic, label=BY_ID[tactic].label, precision=p, recall=r, f1=f, support=n))
    mp, mr, mf, mn = micro(truth, pred)
    ap, ar, af, an = scores(truth, pred, None)
    return DetectorScores(
        name=name,
        rows=rows,
        micro=MetricRow(tactic="micro", label="All tactics (micro)", precision=mp, recall=mr, f1=mf, support=mn),
        any_tactic=MetricRow(tactic="any", label="Any tactic vs. none", precision=ap, recall=ar, f1=af, support=an),
        latency_ms_median=round(latency_ms, 2),
        note=note,
    )


# --- utterance level ---------------------------------------------------------------------


class LlmLabels(BaseModel):
    tactics: list[Literal["urgency", "scarcity", "social_proof", "secrecy", "guarantee", "fomo_regret", "skip_checks", "authority"]]


BASELINE_SYSTEM = f"""You label one sentence said by a caller on an unsolicited investment sales call with the
pressure tactics it uses. A sentence can use none, one or several. Definitions (note the honest look-alikes
that must NOT be labeled):
{labeling_guide()}
Return only the tactic ids that clearly apply; an empty list if none."""


async def llm_baseline(texts: list[str]) -> tuple[list[set[str]], float, int, int]:
    """Gemini zero-shot labels, cached per model+text so reruns don't spend tokens again."""
    s = get_settings()
    llm = fast_llm(s.gemini_api_key, s.tenor_model_fast, 12.0)
    cache_path = RESULTS / "llm_baseline_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    # One line at a time: even 2 at a time (x 2 hedged models) got rate-limited (HTTP 4xx).
    limit = asyncio.Semaphore(1)
    times: list[float] = []
    failures = 0

    async def one(text: str) -> set[str]:
        nonlocal failures
        key = f"{s.tenor_model_fast}|{text}"
        if key in cache:
            times.append(cache[key]["ms"])
            return set(cache[key]["tactics"])
        if not llm.available:
            failures += 1
            return set()
        result, ms = None, 0.0
        for attempt in range(3):  # retry rate-limit and server errors with backoff
            async with limit:
                started = time.perf_counter()
                result = await llm.generate(system=BASELINE_SYSTEM, prompt=f"Sentence: {text}", schema=LlmLabels, stage="eval.llm_baseline")
                ms = (time.perf_counter() - started) * 1000
            if result is not None:
                break
            await asyncio.sleep(4 * 2**attempt)
        if result is None:
            failures += 1
            return set()
        times.append(ms)
        cache[key] = {"tactics": sorted(set(result.tactics)), "ms": round(ms, 1)}
        return set(result.tactics)

    preds = await asyncio.gather(*(one(t) for t in texts))
    cache_path.write_text(json.dumps(cache, indent=1))
    return list(preds), statistics.median(times) if times else 0.0, failures, len(texts)


def utterance_level(classifier: TacticClassifier | None) -> tuple[list[DetectorScores], int]:
    rows = [json.loads(line) for line in (DATA / "test.jsonl").read_text().splitlines() if line.strip()]
    texts = [r["text"] for r in rows]
    truth = [set(r["tactics"]) for r in rows]

    started = time.perf_counter()
    by_rules = [rule_tactics(t) for t in texts]
    rules_ms = (time.perf_counter() - started) * 1000 / len(texts)
    out = [detector_scores("Rules only", truth, by_rules, rules_ms, "High-precision patterns per tactic")]

    if classifier is not None:
        per_line = []
        by_clf = []
        for t in texts:  # one line at a time, as live
            started = time.perf_counter()
            by_clf.append(classifier.predict([t])[0])
            per_line.append((time.perf_counter() - started) * 1000)
        clf_ms = statistics.median(per_line)
        out.append(detector_scores("Classifier only", truth, by_clf, clf_ms, "all-MiniLM-L6-v2 embeddings + logistic regression, local CPU"))
        combined = [a | b for a, b in zip(by_clf, by_rules, strict=True)]
        out.append(detector_scores("Tenor detector (classifier + rules)", truth, combined, clf_ms + rules_ms, "What runs live during a call"))

    preds, llm_ms, failures, n = asyncio.run(llm_baseline(texts))
    note = f"Gemini zero-shot, hedged {get_settings().tenor_model_fast}; {failures} of {n} lines got no answer (counted as none)"
    out.append(detector_scores("LLM zero-shot (Gemini)", truth, preds, llm_ms, note))
    return out, len(rows)


# --- call level --------------------------------------------------------------------------


def script_lines(name: str) -> list[tuple[str, str]]:
    out = []
    for line in (CALLS / "scripts" / f"{name}.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            role, text = line.split(":", 1)
            out.append(("caller" if role.strip() == "CALLER" else "user", text.strip()))
    return out


def expectation(name: str, exp: dict) -> tuple[str, str, str | None, str | None]:
    """kind, expected text, min level, max level (handles the M2/M3 and M4 file formats)."""
    kind = exp.get("kind") or ("manipulative" if name.startswith("scam_") else "honest")
    risk = exp.get("risk", {})
    if kind == "manipulative":
        lo = risk.get("min_level", "high")
        return kind, f"{lo} or above", lo, None
    hi = risk.get("max_level", "medium")
    return kind, f"{hi} or below", None, hi


async def run_call_text(name: str, classifier: TacticClassifier | None, live: bool) -> dict:
    catalog = Catalog.load()
    s = get_settings()
    market = RoutedMarketData(FixtureProvider(catalog), FinnhubProvider(s.finnhub_api_key) if live else None)
    bus = EventBus()
    out = bus.subscribe(ClaimChecked, TacticFlagged, SuggestionsUpdated, RiskUpdated)
    tasks = [
        asyncio.create_task(c.run())
        for c in (
            EntityExtractor(bus, catalog, None),
            OfferTracker(bus),
            ClaimChecker(bus, market),
            ResearchAgent(bus, market, FixtureRegister(catalog), catalog, None),
            PressureDetector(bus, classifier),
            SuggestionEngine(bus, wait_for=("checks", "research", "tactics")),
        )
    ]
    caller_text: dict[str, str] = {}
    t = 0.0
    for i, (role, text) in enumerate(script_lines(name)):
        uid = f"u{i}"
        if role == "caller":
            caller_text[uid] = text
        bus.publish(UtteranceFinal(utterance=Utterance(id=uid, speaker=role, speaker_index=1 if role == "caller" else 0, text=text, t_start=t, t_end=t + 3, is_final=True)))  # type: ignore[arg-type]
        t += 4
        await asyncio.sleep(0.02)
    bus.publish(UtterancesClosed())
    await asyncio.wait_for(asyncio.gather(*tasks), 60)
    out.close()
    events = [e async for e in out]
    risk = next((e for e in reversed(events) if isinstance(e, RiskUpdated)), None)
    return {
        "checks": [e.claim for e in events if isinstance(e, ClaimChecked)],
        "flags": [e.flag for e in events if isinstance(e, TacticFlagged)],
        "max_visible": max((len(e.visible) for e in events if isinstance(e, SuggestionsUpdated)), default=0),
        "risk": risk,
        "caller_text": caller_text,
    }


def call_level(classifier: TacticClassifier | None, live: bool) -> list[CallResult]:
    results = []
    for path in sorted((CALLS / "expected").glob("*.json")):
        name = path.stem
        exp = json.loads(path.read_text())
        kind, expected, lo, hi = expectation(name, exp)
        run = asyncio.run(run_call_text(name, classifier, live))
        level = run["risk"].level if run["risk"] else "low"
        score = run["risk"].score if run["risk"] else 0
        ok = (lo is None or LEVELS.index(level) >= LEVELS.index(lo)) and (hi is None or LEVELS.index(level) <= LEVELS.index(hi))

        # False claims: M4 format (text_contains + metric) or the M3 "checks" list.
        wanted = [c for c in exp.get("false_claims", []) if live or not c.get("needs_live_data")]
        wanted += [{"metric": c["metric"]} for c in exp.get("checks", []) if c.get("status") == "false"]
        false_checks = [c for c in run["checks"] if c.status == "false"]
        caught = sum(
            any(c.metric == w["metric"] and (w.get("text_contains", "").lower() in c.text.lower()) for c in false_checks)
            for w in wanted
        )

        # Tactics per caller line, where the expected file labels them.
        precision = recall = None
        if exp.get("caller_tactics"):
            truth_by_text = {row["text"]: set(row["tactics"]) for row in exp["caller_tactics"]}
            flagged: dict[str, set[str]] = {}
            for f in run["flags"]:
                flagged.setdefault(run["caller_text"].get(f.utterance_id, ""), set()).add(f.tactic)
            texts = list(truth_by_text)
            truth = [truth_by_text[t] for t in texts]
            pred = [flagged.get(t, set()) for t in texts]
            p, r, _, _ = micro(truth, pred)
            # Undefined is not zero: recall needs labeled tactics, precision needs flags.
            recall = r if any(truth) else None
            precision = p if any(pred) else None
        results.append(
            CallResult(
                name=name, kind=kind, hard_honest=bool(exp.get("hard_honest")), expected=expected,
                risk_score=score, risk_level=level, ok=ok, false_claims_expected=len(wanted), false_claims_caught=caught,
                tactic_recall=recall, tactic_precision=precision, max_visible_suggestions=run["max_visible"],
            )  # fmt: skip
        )
        print(f"  {name:<26} {kind:<12} risk {score:>3} {level:<8} expected {expected:<18} {'OK' if ok else 'MISS'}  false claims {caught}/{len(wanted)}")
    return results


# --- audio mode ------------------------------------------------------------------------


async def run_audio(names: list[str]) -> list[str]:
    """Replay calls in real time (4 at a time); returns their call ids."""
    from audio.sources import FileSource
    from pipeline.session import CallSession
    from pipeline.transcriber import DeepgramTranscriber

    s = get_settings()
    classifier = TacticClassifier.load_default()
    limit = asyncio.Semaphore(4)
    ids: list[str] = []

    async def noop(_event: object) -> None:
        return None

    async def one(name: str) -> None:
        async with limit:
            market = RoutedMarketData(FixtureProvider(Catalog.load()), FinnhubProvider(s.finnhub_api_key))
            session = CallSession(
                FileSource(CALLS / f"{name}.wav"), DeepgramTranscriber(s.deepgram_api_key), noop, replay_id=name,
                llm=fast_llm(s.gemini_api_key, s.tenor_model_fast, s.tenor_llm_timeout_s), market=market, classifier=classifier,
            )  # fmt: skip
            ids.append(session.id)
            print(f"  replaying {name} (call {session.id}) ...")
            await session.run()

    await asyncio.gather(*(one(n) for n in names if (CALLS / f"{n}.wav").exists()))
    return ids


def latency_table(call_ids: set[str]) -> list[StageLatency]:
    stages: dict[str, list[float]] = {}
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text().splitlines():
            entry = json.loads(line)
            if entry.get("call_id") in call_ids and entry.get("ok", True) is not False:
                stages.setdefault(entry["stage"], []).append(entry["ms"])
    rows = []
    for stage, values in sorted(stages.items()):
        values.sort()
        rows.append(StageLatency(stage=stage, n=len(values), median_ms=round(statistics.median(values), 1), p95_ms=round(values[max(0, round(0.95 * len(values)) - 1)], 1)))
    return rows


# --- report ----------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", action="store_true", help="also replay the calls in real time through Deepgram")
    ap.add_argument("--live-data", action="store_true", help="use live Finnhub for real tickers in text mode")
    args = ap.parse_args()

    classifier = TacticClassifier.load_default()
    print("Utterance level (held-out lines) ...")
    detectors, n_lines = utterance_level(classifier)
    for d in detectors:
        print(f"  {d.name:<38} P {d.micro.precision:.2f}  R {d.micro.recall:.2f}  F1 {d.micro.f1:.2f}  any-tactic F1 {d.any_tactic.f1:.2f}  {d.latency_ms_median:.1f} ms/line")
    print("Call level (text mode) ...")
    calls = call_level(classifier, args.live_data)

    latency: list[StageLatency] = []
    if args.audio:
        print("Audio mode (real time, Deepgram) ...")
        ids = asyncio.run(run_audio([c.name for c in calls]))
        latency = latency_table(set(ids))

    tenor = next((d for d in detectors if d.name.startswith("Tenor")), detectors[0])
    honest = [c for c in calls if c.kind == "honest"]
    manip = [c for c in calls if c.kind == "manipulative"]
    honest_high = sum(LEVELS.index(c.risk_level) >= LEVELS.index("high") for c in honest)
    fc_exp = sum(c.false_claims_expected for c in calls)
    fc_got = sum(c.false_claims_caught for c in calls)
    e2e = next((row for row in latency if row.stage == "claim.flag_e2e"), None)
    targets = [
        Target(label="Pressure-tactic precision (held-out lines)", target="≥ 0.80", measured=f"{tenor.micro.precision:.2f}", met=tenor.micro.precision >= 0.8),
        Target(label="Pressure-tactic recall (held-out lines)", target="≥ 0.80", measured=f"{tenor.micro.recall:.2f}", met=tenor.micro.recall >= 0.8),
        Target(label="Honest calls rated high risk", target="0 of " + str(len(honest)), measured=f"{honest_high} of {len(honest)}", met=honest_high == 0),
        Target(label="Manipulative calls rated high or critical", target=f"{len(manip)} of {len(manip)}", measured=f"{sum(c.ok for c in manip)} of {len(manip)}", met=all(c.ok for c in manip)),
        Target(label="Scripted false claims caught", target="all", measured=f"{fc_got} of {fc_exp}", met=fc_got == fc_exp),
        Target(label="Claim spoken → verdict (median)", target="≤ 2 s", measured=f"{e2e.median_ms / 1000:.2f} s (n={e2e.n})" if e2e else "not measured (run with --audio)", met=(e2e.median_ms <= 2000) if e2e else None),
        Target(label="Suggestions visible at once", target="≤ 4", measured=str(max(c.max_visible_suggestions for c in calls)), met=max(c.max_visible_suggestions for c in calls) <= 4),
        Target(label="Memo ready after hang-up", target="≤ 60 s", measured="arrives in M5", met=None),
    ]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    report = EvalReport(
        run_id=uuid.uuid4().hex[:8], created_at=utc_now(), commit=commit,
        note=f"{n_lines} held-out lines; {len(calls)} test calls ({len(manip)} manipulative, {len(honest)} honest)"
        + ("; audio replays included" if args.audio else "; text mode (no audio)") + ("; live Finnhub" if args.live_data else ""),
        data=DATA_NOTE, targets=targets, detectors=detectors, calls=calls, latency=latency, audio=args.audio,
    )  # fmt: skip
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "latest.json").write_text(report.model_dump_json(indent=2))
    with sqlite3.connect(RESULTS / "eval.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, created_at TEXT, git_commit TEXT, audio INTEGER, report TEXT)")
        db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", (report.run_id, report.created_at.isoformat(), commit, int(args.audio), report.model_dump_json()))
    print("\nTargets")
    for t in targets:
        status = "met" if t.met else ("not met" if t.met is False else "—")
        print(f"  {t.label:<44} target {t.target:<10} measured {t.measured:<28} {status}")
    print(f"\nSaved run {report.run_id} -> eval/results/latest.json and eval.sqlite")


if __name__ == "__main__":
    main()
