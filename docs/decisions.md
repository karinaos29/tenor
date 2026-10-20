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
