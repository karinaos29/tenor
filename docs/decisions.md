# Decisions

The non-obvious choices, with the reason and the alternative I didn't take. Grouped by topic; the tag shows the milestone. M0–M2 were decided on 2026-10-20, M3–M5 and hosting on 2026-10-21.

**Contents:** [Models](#models-and-providers) · [Audio and speakers](#audio-and-speakers) · [Understanding the call](#understanding-the-call) · [Verifying claims](#verifying-claims) · [Detecting pressure](#detecting-pressure) · [The memo](#the-memo) · [Engineering](#engineering) · [Hosting](#hosting)

## Models and providers
- **Gemini through Google AI Studio, not Claude** `M0`. I already had a billed key. Gemini has a tier for each job, plus structured output. The LLM only extracts and explains, so the provider is easy to swap. *Alternative:* Claude, as first planned; model IDs are config, not code.
- **Fast tiers, no flagship model** `M0`. Flash-Lite handles extraction and wording, and 3.8 Flash only the memo summary. Not `gemini-4-argon`: it sells reasoning depth, and Tenor's LLM is never allowed to reason its way to a verdict. *Alternative:* Argon for the memo, one call per call.
- **Hedged LLM calls** `M3`. Each request goes to 2–3 models at once, and the first valid answer wins. Per-model latency flipped within a day (3.5-flash-lite went from 8–30 s to 0.8 s, 3.1-flash-lite from 1.3 s to 3–19 s). Requests are ~300 tokens, so the extra cost is negligible. *Alternative:* one model with sequential fallback, which waits out the full timeout first.
- **The LLM budget is enforced in the client** `M2`. Gemini rejects an HTTP timeout under 10 s, so the budget (6–20 s per job) is an `asyncio.wait_for`. The thinking level is chosen per model, because 3.8 Flash rejects `minimal` `M5`.
- **Deepgram Nova-3 over a raw WebSocket** `M1`. It documents interim results and diarization, the two things the transcript needs. With the raw socket I control the KeepAlive, reconnects and timeouts. *Alternative:* the Deepgram SDK (that behavior is harder to see and test) or Gemini live transcription (no documented diarization).

## Audio and speakers
- **80 ms frames of 16 kHz PCM from an AudioWorklet** `M1`. That's the same format the replay emits, so mic and replay share the pipeline byte for byte. *Alternative:* MediaRecorder webm/opus, with chunkier latency and a separate path.
- **Browser audio processing off** `M1`. Auto gain would erase the loudness gap between you (near the mic) and the caller (on a phone speaker), which is what the labeler relies on. *Alternative:* browser defaults.
- **Live audio drops, files wait** `M1`. A live call can't pause but a file can. A "fast" replay lost most of the call, because Deepgram transcribes at about real-time speed.
- **Speakers labeled one by one, by loudness** `M1`. Deepgram split one voice into two speaker numbers, so labels are a list (`user_indices`), not one index. A manual swap overrides the labels and locks them. *Alternative:* "the loudest speaker is the user", which is wrong on exactly those cases.
- **Merged voices are split by loudness** `M2`. When one diarized speaker holds a loud and a quiet group at least 6 dB apart, it becomes two voices. On a call with two similar voices, wrong roles fell from 10 of 29 lines to 2. *Alternative:* a spectral cue (phone audio is band-limited), stronger but a new audio feature.

## Understanding the call
- **Rules first, Gemini only for fuzzy lines, quotes enforced** `M2`. Rules fill the offer within ~1 ms and work without a key. Gemini sees only lines with event cues ("signed a deal"), and anything it returns must quote what was actually said. *Alternative:* an LLM on every line, slower and less predictable.
- **The offer comes from the caller's words only** `M2`. You repeating "five thousand shares?" isn't an offer term. Changes are kept as history ("was 5,000"), and the total is computed.
- **Extract per sentence, and finalize after a pause** `M3`. Per stage everything took milliseconds, but a claim inside a long turn took 3.8 s from spoken to flagged. Two fixes brought it to 0.79 s: sentence-level extraction, and asking Deepgram to `Finalize` after a 0.45 s pause. *Alternative:* shorter endpointing, which splits turns everywhere.
- **A claim's subject is the company in its own clause** `M4`. A read-aloud test checked "Apple … up 80%" against the stock on offer. Related fixes from the same test: a ticker is "offered" only when it's introduced or priced; LLM entities fill gaps but never overwrite; lines relabeled as the caller's are reprocessed. *Alternative:* an LLM to resolve the subject, slower and less explainable.

## Verifying claims
- **Research is data first; the LLM only rewords, under a number guard** `M3`. Facts come from providers in ~0.3 s. Gemini's plain-words version is used only if every number in it appears in the data. The planned tool-use agent (3.8 Flash) failed 3 of 3 tries, and the guard caught "thirty-eight cents" and a dropped "−12.5%" on its first run. *Alternative:* an LLM tool-use agent, too unreliable during a call.
- **Verdicts are simple arithmetic** `M3`. A % claim matches if the sign agrees and the gap is ≤ max(3 points, 25%). An offered price must be within 5% of the market. Events are matched against 90 days of news, and the headline is shown, not judged. Guarantees are "Couldn't verify". Generous tolerances avoid accusing an honest caller of rounding.
- **"This quarter" = the last 13 weeks, and labeled as such** `M3`. That's the honest proxy on Finnhub's free tier; fund costs and candles are paid-only, so they show "Couldn't verify".
- **A test register for fictional firms only** `M3`. The scam call can show "not in the register" without a claim about any real firm. Real firms show "Couldn't verify".
- **Suggestions and risk are scored rules** `M3`. Every risk point traces to a listed reason, and a reason never loses points. Risk is shown only once something has been checked, so "Low" never reassures falsely. *Alternative:* an LLM ranking, slower and not explainable.

## Detecting pressure
- **Two AI authors for the benchmark** `M4`. Claude Sonnet wrote the training lines. Claude Haiku wrote the held-out lines and most test calls from a separate brief, without seeing the training data. With one author, a classifier can score well by learning a writer's style. The first run proved it: precision 0.60 on the other author's lines.
- **One round of feedback, disclosed** `M4`. After run 1, I added training lines of the two failure kinds (small talk, same-topic opposites), chose thresholds for F0.5 on training data, and made "strong" need a rule or p ≥ 0.9. The test set never changed, but the numbers are slightly optimistic, and the README says so. *Alternative:* tuning on the test set, which is leakage.
- **The local classifier runs live, although Gemini scores higher** `M4`. Gemini zero-shot reached F1 0.92 vs. 0.84, but at ~660 ms vs. ~9 ms per line, with token costs and per-minute rate limits (429s). Alerts during a call need speed and reliability more than the last few points. *Alternative:* Gemini as an async second opinion, a good next step.

## The memo
- **Built from facts; Gemini words only the summary** `M5`. Every section is deterministic, with its moment in the call and its source. The summary is used only if its numbers come from the facts and it contains none of buy / sell / safe / scam / official; otherwise the template stays. *Alternative:* an LLM-written memo, with nothing to check it against.
- **Hanging up never waits for the memo** `M5`. The writer runs in the background and saves to SQLite, and the browser polls. It's ready ~1 s after hang-up.
- **Email only on an explicit Send** `M5`. Plain HTML, no tracking, and an idempotency key so a double click is harmless. Sending a message is the user's decision. *Alternative:* auto-email on hang-up.

## Engineering
- **TypeScript types generated from the Pydantic events** `M0`. Pydantic → JSON Schema → `json-schema-to-typescript`, strict (no loose index signatures), with a test that fails when they're stale. WebSocket messages aren't covered by OpenAPI codegen.
- **Event bus with a bounded queue per subscriber** `M1`. `publish()` never blocks, and on overflow the oldest event is dropped and logged. It was pulled forward from M2 so components used the bus from day one.
- **An explicit end-of-call chain** `M2`. Each stage publishes a `*.closed` marker, so a slow result can't miss the memo. The M3 test suite found a race where a price check could be lost; `offer.closed` fixed it. *Alternative:* fixed sleeps, either too slow or too short.
- **Latency as JSONL** `M0`. Every stage appends to `backend/logs/latency.jsonl`. It survives crashes and is easy to grep.
- **Test calls voiced by TTS, macOS voices as fallback** `M2`. Scripted calls are reproducible. Gemini TTS stalled after 12 of 42 lines, so the committed WAVs use `say`. The phone side is band-limited and quieter, like a speakerphone.
- **Dark theme inspired by Hiya** `M1`, with Hiya's Branded Call page as the reference. The calm rules still hold: one accent, severity always with a label.

## Hosting
- **The browser talks to the backend directly** `hosting`. The frontend (Vercel) has one build-time setting, `VITE_BACKEND_URL`, for REST and WebSockets. The backend allows that origin (`ALLOWED_ORIGINS`) and checks the `Origin` of both sockets, since CORS doesn't cover WebSockets. Vercel rewrites can't proxy WebSockets. *Alternative:* serving the frontend from FastAPI, one origin but no CDN.
- **A Docker image with CPU-only PyTorch and the model baked in** `hosting`. The default Linux torch pulled CUDA and Triton (17 wheels, 3.0 GB) for a server with no GPU; the CPU wheel is 0.2 GB. The embedding model is downloaded at build time, and the build fails if the classifier can't load offline, because a silent fallback to rules only would cost recall. *Alternative:* Railway's default builder, with no control over either.
