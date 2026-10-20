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
