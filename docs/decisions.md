# Decisions

Non-obvious choices, newest last. Format: decision, why, alternative.

---

### 2026-10-20 · M0 · LLM provider: Google Gemini instead of Claude
- **Decision:** Use Gemini through the `google-genai` SDK with a Google AI Studio key (billing enabled). `ANTHROPIC_API_KEY` in the kickoff prompt becomes `GEMINI_API_KEY`.
- **Why:** I already have a billed AI Studio key, so there's no new account or spend approval. The Gemini line has a tier for each of Tenor's LLM jobs (Flash-Lite for the per-utterance hot path, Flash for tool use), plus structured JSON output and function calling, which is all the architecture needs. The LLM only extracts and explains (verdicts come from data), so the provider is swappable.
- **Alternative:** Claude via the Anthropic SDK, as first planned. Kept possible: model IDs are config, not code.

### 2026-10-20 · M0 · One Gemini model per job, no flagship model
- **Decision:** `gemini-3.5-flash-lite` (thinking `minimal`) for extraction; `gemini-3.8-flash` (thinking `low`) for the research agent; `gemini-3.8-flash` for the memo. Not `gemini-4-argon`.
- **Why:** Extraction runs on every utterance and sits on the "flag within 2 s" path, so it needs the cheapest, fastest tier ($0.30 / $2.50 per 1M in/out). Research needs reliable tool calls, so it gets Flash. Argon ($2 / $10, doubling on 2026-12-01, paid tier only) buys reasoning depth, but Tenor's LLM never decides a verdict, so depth adds little. Prices and IDs checked on ai.google.dev on 2026-10-20.
- **Alternative:** Argon for the memo (one call per session, so cost is small). Revisit if memo quality is weak. Note: 3.8 Flash's price doubles on 2027-01-01; Flash-Lite is the fallback.

### 2026-10-20 · M0 · Keep Deepgram for speech-to-text
- **Decision:** Stay with Deepgram streaming even though Gemini now has `gemini-3.5-transcribe-live`.
- **Why:** Deepgram documents both features M1 depends on: interim results and speaker diarization. Two vendors for two jobs is acceptable.
- **Alternative:** A single-vendor Gemini stack. Revisit in M1 if Deepgram's diarization struggles with speakerphone audio.

### 2026-10-20 · M0 · TypeScript types generated via JSON Schema
- **Decision:** Pydantic models → `TypeAdapter(TenorEvent).json_schema(mode="serialization")` → `json-schema-to-typescript`, run by `npm run gen:types`. The schema JSON is committed next to the generated `.ts`, and a backend test fails when it's stale.
- **Why:** WebSocket messages aren't covered by OpenAPI codegen. Serialization mode plus `json_schema_serialization_defaults_required` makes every field the server always sends required in TS, so there's no `?` on `ts` or `type`. Field titles are dropped (otherwise json2ts makes an alias per field: `Ts1`, `Type2`…), and `--additionalProperties=false` removes the loose `[k: string]: unknown` index signature, so the types are strict enough to catch bad casts. The staleness test enforces the "never hand-write types" rule automatically.
- **Alternative:** `pydantic2ts` (adds a Python dependency and still needs the same Node tool), or OpenAPI codegen (REST only).

### 2026-10-20 · M0 · App-level ping/pong on the health socket
- **Decision:** The client sends `health.ping` every 5 s and the server echoes `client_sent_ms`; the client computes round-trip time. A missing status or pong triggers reconnect with backoff (1 → 10 s).
- **Why:** Browser JS can't see WebSocket protocol pings. This gives a visible round-trip time, a latency-log entry, and a fallback state ("Can't reach Tenor's server") from the first commit.
- **Alternative:** Rely on `onclose` only. That misses half-open connections.

### 2026-10-20 · M0 · Health status reports keys as booleans
- **Decision:** `HealthStatus.services` says which API keys are set (`true/false`), never the values.
- **Why:** The Start screen can show "Key missing" per service before a call starts, instead of failing mid-call.
- **Alternative:** Fail at first use. Worse for Eszter and for reviewers running it without every key.

### 2026-10-20 · M0 · Latency log as JSONL
- **Decision:** `pipeline/latency.py` appends `{ts, stage, ms, ...}` lines to `backend/logs/latency.jsonl` (gitignored), via `timed("stage")` or `record(...)`.
- **Why:** Append-only, survives crashes, easy to grep, and needs nothing new at M0. The M4 eval screen reads it.
- **Alternative:** SQLite now. Deferred to M4, when eval runs need SQLite anyway.

### 2026-10-20 · M0 · Backend is a uv "virtual" project with top-level packages
- **Decision:** `package = false` in `pyproject.toml`; `app/`, `pipeline/`, `audio/` etc. are imported from `backend/` (pytest `pythonpath = ["."]`).
- **Why:** Matches the documented commands exactly (`uvicorn app.main:app`, `python -m audio.replay`) with no install step.
- **Alternative:** `src/` layout with an installable package. More ceremony for a prototype.

### 2026-10-20 · M0 · Event bus waits for M2
- **Decision:** M0 has only the event base class (`pipeline/events.py`); `pipeline/bus.py` arrives in M2.
- **Why:** The milestone plan puts the bus in M2, and the skeleton shouldn't guess its shape before there are two components to connect.
- **Alternative:** Stub the bus now. That would be empty code with no consumer.

### 2026-10-20 · M0 · Same-origin dev setup and self-hosted fonts
- **Decision:** Vite proxies `/api` and `/ws` to `localhost:8000`. Fonts come from `@fontsource` packages.
- **Why:** One origin means no CORS config, and the frontend uses relative URLs. Self-hosted fonts mean no external request at page load, and the demo works offline.
- **Alternative:** CORS middleware, Google Fonts `<link>`.

### 2026-10-20 · M0 · `httpx2` for the test client
- **Decision:** Dev dependency `httpx2` instead of `httpx`.
- **Why:** The installed Starlette warns that `httpx` with its `TestClient` is deprecated in favor of `httpx2`.
- **Alternative:** Pin `httpx` and live with the warning.

---

### 2026-10-20 · M1 · Event bus and a minimal replay pulled into M1
- **Decision:** `pipeline/bus.py` and `FileSource` + one short test call (`m1_hello.wav`) ship in M1, although the plan lists them under M2.
- **Why:** M1 already has three components (transcriber → labeler → panel), and the rule is that components talk only through the bus. The milestone acceptance criteria also require every demo to work on replay. M2 now just adds subscribers and the two full scripted calls.
- **Alternative:** Direct calls in M1, refactored onto a bus in M2. That would be work done twice and would break the rule for a day.

### 2026-10-20 · M1 · Bus: one bounded queue per subscriber, drop oldest
- **Decision:** `publish()` never blocks. Each subscriber has its own queue (1000 events); on overflow the oldest event is dropped and logged.
- **Why:** A slow consumer (the future research agent) must never delay a fast one (the transcript).
- **Alternative:** One shared queue, or blocking publish. Both let one slow stage stall the call.

### 2026-10-20 · M1 · Deepgram Nova-3 over a raw WebSocket
- **Decision:** `wss://api.deepgram.com/v1/listen` with `model=nova-3`, `diarize_model=latest`, `interim_results`, `endpointing=300`, `utterance_end_ms=1000`, `smart_format`, through the `websockets` library (already installed), not the Deepgram SDK.
- **Why:** Deepgram recommends Nova-3 for multi-speaker audio. Its newer Flux model (on `/v2/listen`) is built for voice-agent turn-taking, and its docs don't document diarization. `diarize_model=latest` is the current switch (`diarize=true` is deprecated). With the raw socket I control every timeout, the KeepAlive (every 4 s of silence; Deepgram closes at 10 s), reconnects (3, with backoff, timestamps re-based) and the fallback states. Checked on developers.deepgram.com on 2026-10-20.
- **Alternative:** The Deepgram Python SDK: less code, but its reconnect and timeout behavior is harder to see and test.

### 2026-10-20 · M1 · 80 ms frames of 16 kHz linear16
- **Decision:** Every audio source emits 1280-sample (2560-byte) frames. The browser downsamples in an AudioWorklet.
- **Why:** Inside the architecture's 20–100 ms range, and Deepgram's documented recommendation. One format means mic and replay share the pipeline byte for byte.
- **Alternative:** MediaRecorder webm/opus: simpler in the browser, but chunkier latency and a different path from replay.

### 2026-10-20 · M1 · Browser audio processing off
- **Decision:** `getUserMedia` with `echoCancellation`, `noiseSuppression` and `autoGainControl` all `false`.
- **Why:** AGC would level out exactly the loudness difference the speaker labeler uses (you near the mic, the caller on a phone speaker). Noise suppression can treat speakerphone audio as noise. Echo cancellation has nothing to cancel: the laptop plays no far-end audio.
- **Alternative:** Browser defaults. Revisit if real speakerphone tests show noise problems.

### 2026-10-20 · M1 · Speaker labels: each diarized speaker labeled on its own
- **Decision:** The labeler (not the transcriber) publishes `utterance.*`. `speakers.updated` carries a list, `user_indices`. After 2 s of speech from at least two speakers with a gap of 3 dB or more, every speaker is classified against the loudness midpoint (±1 dB hysteresis). A manual swap inverts and locks, and later speakers are classified against the two hand-labeled groups. Single-word speaker flips are smoothed. Partial lines show no role ("Speaking…") until final.
- **Why:** The first real replay showed Deepgram splitting one voice into two speaker numbers (0 and 2) and giving the caller's first word to the previous speaker. A single "user index" would have relabeled the opening "Hello?" as the caller. Interim speaker numbers also flip before the final result.
- **Alternative:** One user index ("the loudest speaker"): simpler, but wrong on exactly those cases.

### 2026-10-20 · M1 · Live audio drops, files wait
- **Decision:** For real-time sources (mic), the 5 s audio buffer drops the oldest frame when full. For files, the pump waits (backpressure). The replay CLI always plays in real time.
- **Why:** A live call can't pause, but a file can. A "fast" replay lost most of the call: Deepgram's live API transcribes at about real-time speed, so faster input only stalls the end.
- **Alternative:** Batch (pre-recorded) API for fast evaluation runs. Possibly in M4.

### 2026-10-20 · M1 · Test call generated with macOS voices
- **Decision:** `fixtures/calls/make_m1_clip.py` builds `m1_hello.wav` from two `say` voices. The caller is band-limited to 300–3400 Hz and 8 dB quieter, like a phone on speaker.
- **Why:** Free, reproducible, scripted exactly, and it exercises the loudness heuristic. Fictional firm and ticker only.
- **Alternative:** A human recording: more realistic, not reproducible. Still an option for the M2 scripted calls.

### 2026-10-20 · M1 · Dark Hiya-inspired theme
- **Decision:** Dark only: deep indigo surfaces, Hiya-like violet as the single accent, a purple→cyan gradient only on brand moments (wordmark, Start headline). Plus Jakarta Sans (display), Nunito Sans (body), IBM Plex Mono (numbers). The transcript has its own voice tokens (cyan rule for the caller, raised bubble for you). All text is at least 5.4:1 contrast.
- **Why:** Your call, with Hiya's Branded Call page as the reference. The calm rules (one accent, severity always with a text label, motion only for news) still hold.
- **Alternative:** Hiya styling on the Start screen only, or both themes restyled.

### 2026-10-20 · M1 · Generated types: one root object
- **Decision:** `schema_export` emits a root `TenorWire` object referencing `TenorEvent` and the REST payloads (`ReplayList`).
- **Why:** json-schema-to-typescript 16 ignores `--unreachableDefinitions`, so REST models not referenced from the event union weren't generated. A root that references everything makes them all reachable.
- **Alternative:** Hand-writing the REST types. Not allowed by the rules.

---

### 2026-10-20 · M2 · Extraction: rules first, Gemini only for fuzzy lines, quotes enforced
- **Decision:** Rules (regex + number-word normalizer + catalogs) extract every offer term, names, tickers, and the clear claims (price moves, guarantees, fund expense ratios). Gemini runs only on caller lines with company-event cues ("signed a deal") or on the first lines while name or firm is unknown, asynchronously. Anything it returns must quote words that were actually said, or it's dropped. If it fails or times out, the event sentences become rule claims.
- **Why:** The offer card must fill within milliseconds and work without a key. On both scripts, rules alone reproduce the full expected offer. Quote enforcement stops the LLM from inventing claims.
- **Alternative:** LLM for every utterance: slower, costlier, and less predictable (see the latency entry below).

### 2026-10-20 · M2 · Extraction model: `gemini-3.1-flash-lite`, 8 s async budget
- **Decision:** Default `TENOR_MODEL_FAST=gemini-3.1-flash-lite` (was `gemini-3.5-flash-lite`), `TENOR_LLM_TIMEOUT_S=8`, enforced with `asyncio.wait_for`. The HTTP option stays at Gemini's 10 s minimum.
- **Why:** Measured today with identical structured-output requests: 3.1-flash-lite took 1.3–5.4 s (one outlier at 23.8 s), while 3.5-flash-lite took 8–30 s and often timed out. 3.1 is also cheaper ($0.25 / $1.50 per 1M). Gemini rejects an HTTP timeout under 10 s ("Minimum allowed deadline is 10s"), so a 2.5 s HTTP timeout made every call fail. Small samples, so M4 re-measures.
- **Alternative:** Keep 3.5-flash-lite for quality. Not worth it while it can't answer within a call.

### 2026-10-20 · M2 · Entity kinds `person`, `payment`, `fee` added
- **Decision:** Beyond the architecture's `ticker|price|percent|quantity|deadline|firm`.
- **Why:** The wireframe shows the caller's name, and the Offer model has payment and fees fields that need a source.
- **Alternative:** A separate caller-identity event. More plumbing for the same data.

### 2026-10-20 · M2 · Claims extracted but not shown until M3
- **Decision:** `claim.extracted` is published (status `checking`) but not rendered.
- **Why:** With no checker until M3, the UI would show "Checking…" forever, which isn't honest.
- **Alternative:** Show them as "Not checked yet". Noise for Eszter during a call.

### 2026-10-20 · M2 · Offer: caller's words only, computed total, quiet upgrades
- **Decision:** Only `speaker == caller` entities fill the offer. A different value is a `TermChange` ("was 5,000"). The same value heard more clearly (unsure → matched) upgrades without a change event. Total = price × quantity, marked `computed`.
- **Why:** You repeating "five thousand shares?" isn't an offer term. Changes like a doubled quantity are a signal M4 will use.
- **Alternative:** Accept any speaker. Echoes would create fake changes.

### 2026-10-20 · M2 · End-of-call chain
- **Decision:** `transcript.closed` → labeler → `utterances.closed` → extractor (waits for pending LLM calls, ≤ 9 s) → `entities.closed` → offer tracker → `call.ended`.
- **Why:** Without the chain, a slow LLM result or the last utterance could arrive after `call.ended` and be lost to the memo (M5).
- **Alternative:** Fixed sleeps before `call.ended`. Either too slow or too short.

### 2026-10-20 · M2 · Scripted calls voiced by Gemini TTS, per turn, cached
- **Decision:** `make_calls.py` sends one `gemini-3.8-flash-tts` request per turn (Interactions API), one voice per role (Charon for the pushy caller, Leda for the adviser, Sulafat for you), resamples to 16 kHz, applies the same phone simulation as M1, and caches each turn.
- **Why:** Natural voices make the demo and the transcription test realistic. Per-turn generation lets the caller's voice be band-limited separately, and the cache means editing one line re-voices only that line.
- **Alternative:** Multi-speaker TTS in one request: fewer calls, but no per-role processing.
- **What actually happened (2026-10-20):** Gemini TTS voiced 12 of 42 lines, then stopped responding. Requests hung past a 75 s cap and through three retries, and a single two-word probe with SDK retries off didn't return within 60 s either. So the committed WAVs use the **`--voices macos` fallback** (same scripts, processing and levels). Rerunning `make_calls.py` swaps in the Gemini voices with one command; the cache keeps the 12 finished lines. Lesson applied: the generator now has a per-request timeout and retries, as the product's own external calls do.

### 2026-10-20 · M2 · `websockets` 16.x
- **Decision:** Accept `google-genai`'s pin, which downgraded `websockets` 17.3 → 16.1.1.
- **Why:** The transcriber only uses the asyncio client API available since 14.x, and all transcriber tests (including the fake Deepgram server) pass on 16.1.1.
- **Alternative:** Fight the pin. No benefit.

### 2026-10-20 · M2 · Merged voices: split one diarized speaker by loudness
- **Decision:** When one diarized speaker's final turns form a loud and a quiet group at least 6 dB apart (`SPLIT_DB`), the labeler splits it into two voices. The speaker number keeps the group that holds its first turn; the other group gets voice number 100 + n. The loud group is the user. A split needs about a word in the smaller group (0.3 s), 2 s in the larger one, and the two groups must land on opposite sides of the call's loudness midpoint, so no split is made where it wouldn't change a label. After a split, each stretch of that speaker's words between pauses of 0.3 s or more goes to the nearer group, so a turn change Deepgram didn't mark still starts a new line. After a manual swap, no new splits. The event contract is unchanged: `speaker_index` is now a voice number, and the UI relabels by `user_indices` as before.
- **Why:** Deepgram put two similar female voices on one speaker number, so one side of the call took the other's role. The extractor and the offer tracker read the role when a line is sent, so the split has to label the line that reveals it, not only later ones. That's why one word is enough for the smaller group: the user's "Hello?" is 0.4 s in every real replay. Measured live: the honest call re-voiced with two female voices, where Deepgram put both on speaker 1 from 0:03; wrong roles went from 10 of 29 lines to 2 (short fragments on speaker 0). Measured offline, on words, speaker numbers and levels recorded from real replays and fed through the old and the new labeler: the two committed calls come out identical, and with every word moved onto one speaker (the original failure) the old labeler shows no caller line and an empty offer, while the new one reproduces both expected offers exactly. The worst labeler step is 0.4 ms.
- **Alternative:** (1) Re-send earlier lines with a corrected role: fixes the history, but the extractor and the UI would have to handle revised finals (a contract change). (2) Route every turn by its own loudness, ignoring diarization: changes healthy calls, and one voice's word levels spread about ±5 dB. (3) A spectral cue (phone audio is band-limited to 300–3400 Hz): a stronger signal, but a new audio feature; worth it if loudness proves too weak on real speakerphones.

---

### 2026-10-21 · M3 · Research is data first; the LLM only rewords, under a number guard
- **Decision:** When a ticker or firm is first mentioned, the research agent fetches facts from providers (no LLM) and publishes a template summary in ~0.3 s. Gemini then rewrites it in plain words. The rewrite is accepted only if every number in it (after normalizing numbers written as words) appears in the facts, and every percentage from the template is still there. Otherwise the template stays.
- **Why:** Your choice, backed by measurements: `gemini-3.8-flash`, the planned tool-use model, returned 503/504 in 3 of 3 tries, so an LLM-driven agent might never answer during a call. The first real rewording also showed the guard was needed: Gemini wrote numbers as words ("thirty-eight cents"), which would have slipped past a digits-only check, dropped the key "−12.5%", and called a test register "official" (now forbidden in the prompt).
- **Alternative:** A Gemini tool-use agent (the original architecture). More flexible, but too unreliable today.

### 2026-10-21 · M3 · Hedged LLM calls
- **Decision:** `TENOR_MODEL_FAST` is a list (`gemini-3.5-flash-lite,gemini-3.1-flash-lite`). Each request goes to all models at once; the first valid answer wins and the rest are cancelled. Used for extraction and rewording.
- **Why:** Per-model latency flipped within a day: 3.5-flash-lite went from 8–30 s to 0.8 s, 3.1-flash-lite from 1.3 s to 3–19 s. Picking one model by yesterday's numbers would have been wrong today. Requests are ~300 tokens, so double cost is about $0.004 per call.
- **Alternative:** One model with sequential fallback. That waits out the full timeout before trying the second.

### 2026-10-21 · M3 · Finnhub free tier, 13-week return = "this quarter"
- **Decision:** Real tickers use Finnhub `quote`, `stock/metric` (5-day, MTD, 13-week, YTD, 52-week returns), `stock/profile2` and `company-news`. "This quarter" maps to the 13-week return and is labeled as such. Fund costs (ETF profile) and price history (candles) are paid-only (403), so they're "Couldn't verify".
- **Why:** Probed with your key: 200–300 ms each. A trailing 13-week window is the honest free proxy for "this quarter", and the label says exactly which window was used.
- **Alternative:** Paid candles for exact calendar quarters.

### 2026-10-21 · M3 · Verdict rules
- **Decision:** A % claim is "verified" if the sign matches and the gap is ≤ max(3 points, 25% of the claim), otherwise "doesn't match data". An offered price must be within 5% of the market quote. Company events are matched by keywords against 90 days of news: no match = "No evidence found", a match = "Couldn't verify" plus the headline, so you judge it. Guarantees are "Couldn't verify" ("share prices can't be guaranteed").
- **Why:** Simple arithmetic someone can check by hand. Generous tolerances avoid accusing an honest caller of rounding. Headlines are shown, never judged by an LLM.
- **Alternative:** An LLM decides whether a headline confirms the claim. Not allowed by the rules.

### 2026-10-21 · M3 · Fictional firms: a test register
- **Decision:** `fixtures/register.json` stands in for a regulator register, for fictional firms only. Real or unknown firms are "Couldn't verify", and the source is labeled "Tenor test register (fictional firms only)".
- **Why:** Lets the scam call show "not in the register" without a claim about any real firm.
- **Alternative:** Scrape a real register: out of scope and fragile.

### 2026-10-21 · M3 · Suggestions and risk are scored rules
- **Decision:** "Say this" lines are fixed first-person templates with priorities: a false claim 100, firm not registered 90, guarantee 85, same-day deadline 80, no evidence 75, price mismatch 70, risky payment 65, amount raised 60. At most 2 are visible, research cards fill the rest of the 4 slots, and "say this" lines expire after 2 minutes. Risk is a capped sum of listed reasons (30/25/15/10…), with levels at 25/50/75. It's shown only once something has been checked.
- **Why:** Deterministic and explainable; every point traces to a reason. Mixing advice and evidence follows the wireframe. Showing "Low" before anything is checked would falsely reassure.
- **Alternative:** An LLM ranks suggestions. Slower, and not explainable.

### 2026-10-21 · M3 · Labeler fix merged before M3
- **Decision:** `main` fast-forwarded to `labeler/split-merged-voices` (a merged speaker is split by per-utterance loudness).
- **Why:** Your call. M3's demo depends on which lines count as the caller's.
