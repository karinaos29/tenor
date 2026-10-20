# AI in Tenor

Two separate questions: **which AI tools I used to build Tenor**, and **which AI models Tenor itself runs on**. Both are about spending tokens where they buy quality, and not spending them where they don't.

Status labels: **Used** = happened, with numbers where I have them. **Built** = in the code now. **Planned** = designed, lands in the milestone shown.

---

## 1. Building Tenor: Claude Code with model routing

My coding agent is **Claude Code** (desktop app). I don't run every task on the strongest model. Each task goes to the cheapest model that can do it reliably, and the expensive model handles the decisions that are hard to undo.

### Durable context instead of repeated prompts
- `CLAUDE.md` holds the rules, stack and layout. Every session reads it automatically, so I never re-explain the project.
- Two project skills load only when needed: `tenor-milestone` (plan, build, verify, document, commit) and `tenor-ui` (design tokens, copy rules, accessibility checklist).
- One milestone per session keeps each conversation short. Context that should last goes into files (`docs/decisions.md`, `docs/milestones/`), not chat history.

### Who did what in M0 (Used)

| Task | Model | Effort | Why this model |
|---|---|---|---|
| Read the spec, plan the skeleton, design events and type generation, backend code, decisions log, review | **Opus 5.5** (main session) | session default | Judgment-heavy and cross-cutting: a bad event model or type pipeline spreads to every later milestone. |
| Web research: current Gemini model IDs, prices, thinking controls | **Haiku 5.5** subagent, in background | low | Reading docs pages produces lots of text, and I needed a short table back. The raw pages stay out of the main context, and Haiku tokens cost a fraction of Opus tokens. Cost: 55.9k tokens, 8 tool calls, 33 s. |
| Fact check of that research | Opus + `curl`/`grep` of the raw docs HTML | — | Haiku read the pages through a summarizer, and model IDs are load-bearing. A wrong ID breaks the app. A grep of the raw page text was cheaper than re-researching. Result: all of Haiku's model IDs were correct. |
| Frontend scaffold from a written spec (Vite, tokens, socket client, store, tests) | **Sonnet 5.5** subagent, in background | medium | Many files, little ambiguity. With a tight brief (files, scripts, states, exact copy, done-criteria) Sonnet doesn't need Opus. It ran while I wrote the backend tests and docs, so the work happened in parallel. Cost: 63.3k tokens, 9 tool calls, ~2 min. All its commands passed on the first run. |
| Review of Sonnet's output | Opus (main session) | session default | Cheap models write code that works, so the expensive model reviews for contract quality. It caught three things, fixed in ~10 min: (1) the generated TS types were noisy (`Ts1`, `Type2`, loose `[k: string]: unknown`), fixed at the source by dropping Pydantic field titles and setting `additionalProperties=false`; the stricter types then caught two unsafe casts, so parsing moved to the socket boundary; (2) the first ping waited 5 s, so the response time showed late; (3) services said "Checking…" while offline, changed to "Not checked". |
| Visual check (light/dark, 1280/900 px, offline and recovery), final test run, commit | Opus (main session) | session default | Short, and needs judgment on the design rules. |

### Who did what in M1 (Used)

| Task | Model | Effort | Result |
|---|---|---|---|
| Deepgram streaming research (model, diarization params, KeepAlive, pricing) | **Haiku 5.5** subagent | low | 68.6k tokens, 12 tool calls, 45 s. This time it read **raw page text with `curl`**, not a summarizer (lesson from M0). I re-checked the one surprising string (`diarize_model=latest`) in its saved raw HTML. It was right. |
| Architecture .docx → `docs/architecture.md` | **no model**: `pandoc` | — | Zero tokens. A converter does this better than any model. |
| Plan, events, bus, transcriber, speaker labeler, session, gateway, test clip | **Opus 5.5** (main session) | session default | The correctness-critical core. Running the real replay early found 4 bugs that only real audio shows (a voice split into two speakers, a leading-word mislabel, interim label flips, the fast-replay data loss). |
| Frontend: dark Hiya theme, Start/Live screens, AudioWorklet capture, call socket, 36 tests | **Sonnet 5.5** subagent, background | medium | 96.3k tokens, 16 tool calls, ~4 min, all checks passing on its first report. Ran in parallel with my backend work. |
| Backend test suite (bus, sources, transcriber against a fake Deepgram server, labeler, gateway, opt-in live test) | **Sonnet 5.5** subagent, background | medium | 95.5k tokens, 12 tool calls, ~4.4 min, 79 tests. Told to **report bugs, not patch around them**: it found 2 real bugs in my (Opus) code, held as strict xfails until I fixed them. |
| Review of Sonnet's frontend + transcript restyle you asked for | Opus | session default | Checked the worklet buffer handling and the socket lifecycle. Restyled the transcript with voice tokens (contrast computed, not eyeballed). |

**What M1 showed about routing:** cross-model review works both ways. Opus caught Sonnet's contract-level issues in M0. In M1, Sonnet's independent tests caught Opus's edge cases. Each model checks work it didn't write.

### Who did what in M2 (Used)

| Task | Model | Effort | Result |
|---|---|---|---|
| Gemini SDK and TTS API check (thinking config, schema, multi-speaker) | **no subagent**: `uvx` + `grep` on raw docs | — | Two targeted checks were cheaper than a research agent this time. |
| Scripts, ground truth, number normalizer, extraction rules, LLM contract, offer tracker, session chain, TTS generator | **Opus 5.5** (main session) | session default | The scripts came first, so rules were built against the ground truth. Rules alone reproduce both expected offers. |
| Offer card, caller strip, transcript highlights, 13 tests | **Sonnet 5.5** subagent, background | medium | 67.1k tokens, 7 tool calls, ~1 min. Reviewed by Opus; no changes needed. |
| Backend test suite (normalizer, rules incl. negative cases, extractor with a fake LLM, LLM wrapper, tracker, scripts vs. ground truth, session wiring) | **Sonnet 5.5** subagent, background | medium | 108.7k tokens, 17 tool calls, ~3 min, 206 tests, no source bugs found this time. |
| Real-audio verification | Opus + Deepgram + Gemini | — | Found what tests on text couldn't: Deepgram merged two similar voices into one speaker, misheard "is this Eszter?" as a name, and wrote "a quarter percent" as "025%". Gemini rejected HTTP timeouts under 10 s and its TTS stalled. Each finding is now a fix, a regression test, or a documented follow-up. |

**What M2 showed about routing:** the most valuable "model" step was running the real pipeline on real audio. Five of the M2 bugs only appeared there. Cheap models write good tests against the spec, but only reality tests the spec itself.

### Habits that save tokens (Used)
- **Complete briefs for subagents.** A cold subagent re-reads context, so each brief names the files, the commands that must pass, and the exact UI copy. That saves the back-and-forth.
- **Background, not blocking.** Research and scaffolding ran while the main session kept working.
- **Verify the expensive-to-be-wrong facts, trust the rest.** Model IDs and prices were checked against raw docs. Routine things (package versions) are left to `npm install` / `uv add`.
- **Targeted reads.** I extracted only the relevant passages of the docs pages (models, pricing, thinking, caching) instead of loading whole pages.
- **Generated types.** TypeScript event types come from the Pydantic models (`npm run gen:types`), so no model writes them twice and they can't drift. A test enforces this. In M1 they caught every stale use of a renamed field (`user_index` → `user_indices`) at typecheck time.
- **Tools before models.** `pandoc` for document conversion, `curl` + `grep` for exact strings, `say` for test audio. A model only where judgment is needed.
- **Disjoint files for parallel agents.** The frontend agent touched only `frontend/`, the test agent only `backend/tests/`, and I touched the source. No merge conflicts, no re-reading each other's work.

### Routing plan for the next milestones (Planned)
- **M2 Understand:** Opus for the extraction contract (what counts as a claim; regex-first, Gemini only for fuzzy cases) and the offer state machine. Sonnet for the offer card UI and tests. The two scripted calls generated with tools, not a model.
- **M3:** Opus for the claim-check arithmetic and suggestion ranking. Sonnet for provider adapters and fixtures once the interface is fixed.
- **M4:** Haiku or Sonnet to summarize eval runs and draft labeled utterances for me to review. Opus for the metrics and the classifier-vs-LLM comparison.

---

## 2. Running Tenor: which models, for which job

**The LLM extracts and explains. It never decides a verdict.** Claim verdicts come from data and arithmetic. This rule drives the model choices: Tenor doesn't need a flagship reasoning model, it needs fast, cheap, structured extraction.

| Job | Model | Settings | Why | Status |
|---|---|---|---|---|
| Speech-to-text, both sides, live | Deepgram **Nova-3** streaming (`/v1/listen`) | interim results, `diarize_model=latest`, endpointing 300 ms | Deepgram's recommendation for multi-speaker audio; measured 305 ms median to interim words. ~$0.0077/min + $0.0020/min diarization (list price) | **Built** (M1) |
| Offer terms, names, tickers, clear claims (price moves, guarantees, fund fees) | **no model**: rules + number-word normalizer + catalogs | — | ~1 ms per utterance, works without a key; reproduces the full expected offer on both test calls | **Built** (M2) |
| Fuzzy extraction: company events ("signed a deal"), names rules missed | `gemini-3.1-flash-lite` | thinking `minimal`, Pydantic `response_schema`, 8 s async budget, quotes must match what was said | Only on caller lines with event cues: 2 calls on the 3-minute scam call. Measured 1.3–5.4 s, ~260 tokens in / ~70 out. Chosen over 3.5-flash-lite, which took 8–30 s (see below) | **Built** (M2) |
| Research agent (looks up firm, ticker, register, news via tools) | `gemini-3.8-flash` | thinking `low`, function calling | Needs reliable multi-step tool use. Flash, not Lite | Planned (M3) |
| Who is "You" vs. "Caller" | **no model**: loudness per diarized speaker + first-turn rule | — | Deterministic, < 1 ms, explainable; a manual swap overrides it | **Built** (M1) |
| Voices for the scripted test calls (dev time) | `gemini-3.8-flash-tts`, macOS `say` as fallback | one request per turn, 3 voices, cached per line, 75 s cap + retries | Natural voices for a realistic demo and transcription test. **On 2026-10-20 the service stalled after 12 of 42 lines**, so the committed WAVs use the macOS fallback; one command re-voices them when TTS responds | Partly used (M2) |
| Pressure-tactic detection | sentence-transformers embeddings + logistic regression (local) | — | No API cost, millisecond latency, works offline, measurable | Planned (M4) |
| Tactic baseline for the eval | `gemini-3.5-flash-lite` zero-shot | — | The honest comparison: is a trained small classifier better than prompting? | Planned (M4) |
| Decision memo after hang-up | `gemini-3.8-flash` | thinking `medium` | One call per session. Quality matters more than speed, but it only explains facts already checked | Planned (M5) |

Model IDs live in `backend/app/config.py` and can be overridden from `.env` (`TENOR_MODEL_FAST`, `TENOR_MODEL_RESEARCH`, `TENOR_MODEL_MEMO`, `TENOR_LLM_TIMEOUT_S`). **Built** in M0.

### What M2 measured about Gemini (Used)
Identical structured-output requests, 2026-10-20, from my laptop:

| Model | Latency (n) | Notes |
|---|---|---|
| `gemini-3.1-flash-lite` | 1.3, 3.1, 3.7, 5.4 s; one 23.8 s outlier (5) | ~260 input / ~70 output tokens, no thinking tokens |
| `gemini-3.5-flash-lite` | 8–30 s, mostly server timeouts (6) | |
| `gemini-3.8-flash` | timed out at 30 s (1) | Planned research model: re-check before M3 |

Two lessons that changed the code:
1. **A model on the hot path is a liability.** This is why the architecture says "rules first": the offer card never waits for an LLM, and the extraction LLM is an async extra with a fallback. The architecture's "50–500 ms" for the LLM step isn't achievable with these numbers. The rules step achieves ~1 ms.
2. **Gemini's HTTP timeout is a server deadline with a 10 s minimum.** A 2.5 s `HttpOptions(timeout=…)` made every call fail with 400 INVALID_ARGUMENT. The real budget is now enforced client-side with `asyncio.wait_for`.

### Why Gemini through Google AI Studio
- **I already have a billed Google AI Studio key.** One key covers every LLM job, with no new vendor account. The SDK is `google-genai` and reads `GEMINI_API_KEY`.
- **There's a tier for each job.** Flash-Lite for the hot path, Flash for tool use, both with structured output and function calling.
- **Why not the flagship `gemini-4-argon`:** $2 / $10 per 1M tokens (doubling to $4 / $20 on 2026-12-01), paid tier only. It buys deep reasoning, but the LLM in Tenor isn't allowed to reason its way to a verdict. Kept as a one-line config switch for the memo if quality is lacking.
- **Watch item:** `gemini-3.8-flash` doubles to $1.50 / $7.50 on 2027-01-01. Flash-Lite is the fallback for research if that matters.
- **Originally planned:** Claude via the Anthropic SDK. Switched because of the existing key (see `docs/decisions.md`).

Prices, IDs, thinking levels and caching limits were checked on ai.google.dev ([models](https://ai.google.dev/gemini-api/docs/models), [pricing](https://ai.google.dev/gemini-api/docs/pricing), [thinking](https://ai.google.dev/gemini-api/docs/thinking), [caching](https://ai.google.dev/gemini-api/docs/caching)) on 2026-10-20.

### Token and latency budget at runtime
- **Rules before tokens (Built, M2).** Most utterances never reach an LLM. On the 3-minute scam call, 2 of 12 caller lines did (the "signed a deal" lines).
- **Thinking off (Built, M2).** Thinking tokens are billed as output. Extraction uses `minimal`, and the measured calls used 0 thinking tokens.
- **Send the delta, not the transcript (Built, M2).** Each extraction call gets one sentence plus the current instrument (~260 tokens), not the whole call. Cost stays flat as the call gets longer.
- **Stable prefix first.** Instructions, schema and tool definitions go at the start of every prompt so implicit caching (on by default for Gemini 2.5+) can apply. Honest caveat: the minimum for 3.8 Flash is 4,096 tokens, so the research agent's prompt (tool definitions + call context) is the likely beneficiary. Flash-Lite isn't in Google's minimums table, and the short extraction prompts probably won't cache.
- **Structured output, no retries.** Responses are validated against the same Pydantic models as the events. A malformed response gives a "couldn't verify" state, not a retry loop.
- **Prefetch research.** The research agent starts when a firm or ticker is first named, before the caller makes a claim about it, so the answer is often ready when needed.
- **Log tokens next to latency.** Each LLM stage records input, output and cached tokens from the response's usage data in the same latency log. The eval screen can then show real cost per call, not just this estimate.

**Rough cost of one 15-minute call (estimate; the extraction row uses M2's measured tokens, the others are still assumptions).** Extraction: ~10 LLM calls × ~260 input / ~70 output tokens. Research: ~5 runs × 3 turns × ~3k / ~500. Memo: ~10k / ~1.5k:

| Stage | Input | Output | Cost |
|---|---|---|---|
| Extraction (3.1 Flash-Lite, rules do the rest) | 2.6k | 0.7k | ≈ $0.002 |
| Research (3.8 Flash) | 45k | 7.5k | ≈ $0.06 |
| Memo (3.8 Flash) | 10k | 1.5k | ≈ $0.01 |
| **Total** | | | **≈ $0.07 per call** |

At these prices, model choice matters more for **latency** (2-second flag target) than for cost. M2 showed that even the fastest tier can take seconds, so the hot path has no model on it at all.
