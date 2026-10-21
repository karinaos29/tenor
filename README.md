# Tenor

**A live copilot for high-pressure investment sales calls.** Put the call on speaker; Tenor listens through the laptop microphone, transcribes both sides, checks the caller's claims against market data, flags pressure tactics as they happen, suggests what to say back, and writes a decision memo after you hang up.

Built for Eszter, 58, a retired teacher with savings: plain words, calm by default, glanceable. Tenor never says "buy" or "sell"; it shows facts and flags and leaves the decision to her.

![The live screen during a pushy share offer: risk Critical, a false claim flagged, suggestions and research](docs/img/live-call.jpg)

*Prototype for the Hiya Voice AI Challenge. No real telephony: microphone input and recorded-call replay, through the same pipeline.*

## What it does
- **Live transcript** of both sides, labeled "You" / "Caller" from loudness (you're next to the mic, the caller is on a phone speaker), with a manual "Swap speakers".
- **The offer card** fills in as the caller talks (who, what, price, quantity, total, deadline, payment) and marks changes ("10,000 shares, was 5,000").
- **Claims vs. data:** "up 40% this quarter" is checked against market data in **0.71 s** median from the moment it's spoken. Verdicts come from data and arithmetic, never from an LLM: "Doesn't match data", "No evidence found", "Couldn't verify".
- **Research while you talk:** is the firm in the register, how has the stock really done.
- **Pressure tactics** (rushing you, keeping it secret, "everyone's doing it", promises no risk, …) are flagged from each sentence by a local classifier plus rules.
- **Up to 4 suggestions:** what to say back ("I don't make decisions on the same day…") and the evidence. A **risk level** rises with its reasons listed.
- **A decision memo** about a second after hang-up (0.9 s median): what was offered, what didn't match, the pressure, questions to ask, and steps that help, each linked to its moment in the call. It can be emailed.
- **"How Tenor is measured":** an in-app evaluation screen for reviewers.

## Quickstart
Requires Python 3.12 via [uv](https://docs.astral.sh/uv/) and Node 22+. Keys go in `.env` (all optional; the Start screen shows what's ready): Deepgram (speech-to-text), Gemini via Google AI Studio (wording), Finnhub (market data), Resend (email).

```bash
cp .env.example .env
```

Backend, from `backend/`:

```bash
uv run uvicorn app.main:app --reload
```

Frontend, from `frontend/` (first time: `npm install`):

```bash
npm run dev
```

Open http://localhost:5173 → **Replay a test call** → **Pushy share offer**. Or tick the consent box, check the microphone, and press **Start listening** with a phone call on speaker. Without the browser (same pipeline, prints transcript, verdicts, memo and latencies), from `backend/`:

```bash
uv run python -m audio.replay fixtures/calls/scam_kstl.wav
```

## How it works
![System overview](docs/img/system-overview.png)

One pipeline for live mic and replay. After transcription, components talk **only through a typed async event bus** (`backend/pipeline/bus.py`); every event is a Pydantic model, and the TypeScript types are generated from them.

| Component | What it does | How | Measured |
|---|---|---|---|
| Audio source | 80 ms frames of 16 kHz PCM from the browser mic (AudioWorklet) or a WAV | `audio/sources.py` | — |
| Transcriber | Deepgram Nova-3 streaming with diarization; KeepAlive, reconnects, and `Finalize` after a pause | `pipeline/transcriber.py` | words on screen ~0.3 s |
| Speaker labeler | Diarized speakers → You / Caller by loudness + first-turn rule; splits merged voices | `pipeline/speakers.py` | < 1 ms |
| Entity extractor | Offer terms, names, tickers, claims: rules first, Gemini only for fuzzy lines (quotes enforced) | `pipeline/extractor.py` | ~1 ms (rules) |
| Offer tracker | The offer as state, with changes; total = arithmetic | `pipeline/offer.py` | < 1 ms |
| Claim checker | Claims vs. Finnhub / test data, by arithmetic | `pipeline/checker.py` | < 1 ms + provider ~0.3 s |
| Research agent | Prefetch on first mention: register, price history, news; Gemini rewords under a number guard | `pipeline/research.py` | ~0.3 s |
| Pressure detector | MiniLM embeddings + logistic regression + rules, per sentence | `pipeline/tactics.py`, `detector/` | ~9–20 ms |
| Suggestions + risk | Ranked "say this" lines + evidence (≤ 4), risk = listed reasons | `pipeline/suggestions.py` | < 1 ms |
| Memo writer | Built from facts after hang-up; Gemini words the summary under guards; SQLite; email via Resend | `memo/` | ~1 s after hang-up |

The full design is in [`docs/architecture.md`](docs/architecture.md).

| After the call: the memo | For reviewers: how Tenor is measured |
|---|---|
| ![Decision memo](docs/img/memo.jpg) | ![Evaluation screen](docs/img/evaluation.jpg) |

## Results
From the latest evaluation run (`eval/results/latest.json`, also shown in the app). This is a **synthetic benchmark**: training lines were written by one AI model (Claude Sonnet), the held-out lines and most test calls by another (Claude Haiku) without access to the training set, and the calls are voiced by text-to-speech. It is not real-world accuracy.

| Target | Goal | Measured |
|---|---|---|
| Pressure-tactic precision / recall (80 held-out lines) | ≥ 0.80 / ≥ 0.80 | **0.84 / 0.85** |
| Honest calls rated high risk | 0 of 7 | **0 of 7** |
| Manipulative calls rated high or critical | 5 of 5 | **5 of 5** |
| Scripted false claims caught | all | **7 of 7** |
| Claim spoken → verdict (median, real audio) | ≤ 2 s | **0.71 s** |
| Memo ready after hang-up (real calls) | ≤ 60 s | **0.9 s** median, p95 9.1 s |
| Memos with no buy / sell / safe / scam wording | all | **12 of 12** (+ 12 of 12 Gemini summaries) |
| Suggestions visible at once | ≤ 4 | 4 |

**The honest comparison:** Gemini zero-shot labels pressure tactics *more accurately* (F1 0.92 vs. 0.84), but it is ~75× slower per sentence and rate-limited, so the local classifier runs live. Details, caveats and the one disclosed round of feedback are in [`docs/milestones/m4.md`](docs/milestones/m4.md).

## Decisions that shaped it
- **The LLM never decides.** Verdicts, risk and the memo's facts come from data and rules; Gemini extracts fuzzy cases and words summaries, only under guards (quotes must match what was said, numbers must come from the facts, no advice words).
- **Hedged LLM calls.** Gemini's per-model latency swung from under 1 s to 30 s in a day, so each request goes to two or three models and the first valid answer wins.
- **Measure end to end.** Per stage everything took milliseconds, but "claim spoken → flagged" was 3.8 s. Two fixes (sentence-level extraction, a Deepgram `Finalize` after a pause) brought it to 0.71 s.
- **Two AI authors for the benchmark,** so a classifier can't score well by learning one writer's style. It caught over-optimistic thresholds on the first run.
- **Real audio beats text tests.** Replays found what unit tests couldn't: merged voices, misheard names, "025%" for 0.25%, a claim checked against the wrong company.

All decisions with reasons and alternatives: [`docs/decisions.md`](docs/decisions.md).

## Limitations
- Synthetic benchmark (see above); 12 scripted calls.
- The firm register is a **test register of fictional firms**; real firms show "Couldn't verify". Fund cost data needs a paid Finnhub plan.
- Within full calls, tactic recall is lower than on single lines (0.40–0.50 on two scam calls; their risk still reaches critical).
- Diarization of two similar voices on one speakerphone is the weakest link; the labeler compensates by loudness, and "Swap speakers" is always there.
- The live microphone path is tested with a real speakerphone only by hand.

## AI in this project
How Claude (Opus, Sonnet, Haiku) built Tenor, with real token counts per milestone, and which models Tenor uses at runtime and why: [`ai.md`](ai.md).

## Milestones
Each milestone is a git tag with a write-up of what was built and measured:
[m0 skeleton](docs/milestones/m0.md) · [m1 hear](docs/milestones/m1.md) · [m2 understand](docs/milestones/m2.md) · [m3 verify](docs/milestones/m3.md) · [m4 detect](docs/milestones/m4.md) · [m5 deliver](docs/milestones/m5.md). The demo video script is in [`docs/demo-script.md`](docs/demo-script.md).

## Test and evaluate
Tests, from `backend/` and `frontend/`:

```bash
uv run pytest
```

```bash
npm run test && npm run typecheck
```

Opt-in tests against real services: `uv run pytest -m deepgram`, `-m finnhub`, `-m model`.

Train the tactic classifier and run the full evaluation (12 calls, real-time audio replays), from `backend/`:

```bash
uv run python ../eval/train_detector.py
```

```bash
uv run python ../eval/run_eval.py --audio --live-data
```

Test calls live in `backend/fixtures/calls/` (scripts, expected results, audio). To re-voice them after editing a script, from `backend/` (Gemini TTS, or `--voices macos`):

```bash
uv run python fixtures/calls/make_calls.py
```

## Docs
- [`docs/architecture.md`](docs/architecture.md): components, events, UI, milestones
- [`docs/tactics.md`](docs/tactics.md): the pressure-tactic taxonomy
- [`docs/decisions.md`](docs/decisions.md): every decision, with why and the alternative
- [`docs/demo-script.md`](docs/demo-script.md): the demo video script
- [`ai.md`](ai.md): AI tools and models, build time and runtime
- [`CLAUDE.md`](CLAUDE.md): rules and stack
