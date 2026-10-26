# Architecture

Tenor runs one pipeline from speech to a live panel and a post-call memo. The laptop microphone listens to a call on speaker, or a recorded call is replayed through the same path.

**Contents:** [Principles](#principles) · [Overview](#overview) · [Components](#components) · [Events](#events) · [When things fail](#when-things-fail) · [Screens](#screens)
Related: [decisions](decisions.md) (why each choice) · [milestones](milestones.md) (how it was built)

## Principles
1. **One pipeline, swappable inputs.** Live mic and replay share every stage after the audio source, so the demo never depends on luck.
2. **Facts are computed, not generated.** A verdict like "claimed +40%, data says −12.5%" comes from data and arithmetic. The LLM extracts and explains, and never decides.
3. **Every result shows its source.** Missing data reads "Couldn't verify", never a guess.
4. **Calm by default.** At most four suggestions, severity always paired with a text label, motion only for news.
5. **Measured, not claimed.** Every stage logs its latency, and the evaluation screen reports the results.

## Overview
![System overview: 2 inputs, 1 event bus, 2 outputs](img/system-overview.png)

The browser streams 80 ms frames of 16 kHz audio over a WebSocket; a replay feeds a WAV file into the same gateway. After transcription, components talk **only through a per-call async event bus**. Each subscriber has its own bounded queue, so a slow stage (research) can't hold up a fast one (the transcript). The suggestion engine decides what reaches the panel.

## Components
One Python module per job, each tested and timed on its own.

| Component | Job | How | Code |
|---|---|---|---|
| Audio source | Mic frames from the browser, or a WAV at real-time pace | AudioWorklet (browser processing off); `FileSource` | `audio/sources.py` |
| Transcriber | Interim and final words with diarized speakers | Deepgram Nova-3 over a raw WebSocket; KeepAlive, 3 reconnects, `Finalize` after a 0.45 s pause | `pipeline/transcriber.py` |
| Speaker labeler | Diarized speakers → "You" / "Caller" | Live: each stretch matched against the user's voice print from the mic check (WavLM). Replays: bass vs. telephone band, then loudness and a first-turn rule; splits merged voices. Manual swap always | `pipeline/speakers.py`, `pipeline/voiceprint.py` |
| Entity extractor | Offer terms, names, tickers, claims, per sentence | Rules + number normalizer first; Gemini only for fuzzy lines, quotes must match | `pipeline/extractor.py` |
| Offer tracker | The current offer and how it changed | State machine, caller's words only; total by arithmetic | `pipeline/offer.py` |
| Claim checker | Claim vs. data | Arithmetic on Finnhub or fixture data | `pipeline/checker.py` |
| Research agent | Firm register, real price history, news; prefetched on first mention | Data first; Gemini rewords under a number guard | `pipeline/research.py` |
| Pressure detector | 8 tactics per caller sentence | MiniLM embeddings + logistic regression, plus rules | `pipeline/tactics.py`, `detector/` |
| Suggestion engine | "Say this" lines + evidence (≤ 4) and the risk score | Scored rules; risk = capped sum of listed reasons | `pipeline/suggestions.py` |
| Memo writer | The decision memo after hang-up | Built from facts; Gemini words only the summary, under guards; SQLite; email via Resend | `memo/` |

Market data sits behind one `MarketDataProvider` interface: `FinnhubProvider` for real tickers and `FixtureProvider` for the fictional companies used in scam scenarios.

## Events
Every event is a Pydantic model with a timestamp (`pipeline/events.py`). The TypeScript types are generated from these models, and a test fails if they're stale.

| Event | From | To |
|---|---|---|
| `transcript.segment` / `transcript.closed` | Transcriber | Speaker labeler |
| `utterance.partial` / `.progress` / `.final`, `speakers.updated` | Speaker labeler | Extractor, pressure detector, checker, panel |
| `entity.detected` | Extractor | Offer tracker, research agent |
| `claim.extracted` | Extractor | Claim checker |
| `offer.updated` / `offer.changed` | Offer tracker | Checker (price), suggestion engine, panel |
| `claim.checked` | Claim checker | Suggestion engine, panel |
| `research.ready` | Research agent | Suggestion engine, panel |
| `tactic.flagged` | Pressure detector | Suggestion engine, panel |
| `suggestions.updated` / `risk.updated` | Suggestion engine | Panel |
| `call.ended` → `memo.ready` | Session → memo writer | Memo screen (polls REST) |

`utterance.progress` carries finished sentences of a turn that's still going, so a claim is checked before the caller stops talking.

**End of call.** Each stage closes in order, so nothing that's still running is lost: `transcript.closed` → `utterances.closed` → `entities.closed` → `offer.closed` → `checks.closed` / `research.closed` / `tactics.closed` → `call.ended`. The memo is then written in the background, so hanging up never waits for an LLM.

## When things fail
Every external call has a timeout and a visible fallback.

| Failure | Fallback |
|---|---|
| Deepgram drops or stalls | 3 reconnects with backoff; "Transcription paused" in the UI |
| Gemini slow or down | Requests hedged across 2–3 models; a client-side budget; the rules or template result stays |
| No market data | "Couldn't verify", with the source named |
| Diarization mixes up speakers | Voice print from the mic check; else bass and loudness, merged-voice split; "Swap speakers" button |
| Misheard ticker or name | Matched against known tickers and company names |
| Classifier can't load | Rules only; the Docker build fails instead, so it can't happen silently in production |

## Screens
| Screen | What it shows |
|---|---|
| Start | Consent, mic check, service status, "Start listening" or "Replay a test call" |
| Live | Call strip with risk, transcript, suggestions, offer, claims, pressure tactics |
| Memo | The decision memo; each item links to its moment in the transcript; email and print |
| Evaluation | For reviewers: targets, detector vs. Gemini, per-call results |

![The live screen during a pushy share offer](img/live-call.jpg)

The design is a dark theme inspired by Hiya's brand. There's one accent color (violet) for Tenor's own suggestions. Red, amber and green are reserved for severity, always with a text label. "Say this" lines use the largest body text, because they're read aloud mid-call. Wording is plain: "Doesn't match data", not "claim falsified". Design tokens and UI rules: `.claude/skills/tenor-ui/SKILL.md`.
