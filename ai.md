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

### Habits that save tokens (Used)
- **Complete briefs for subagents.** A cold subagent re-reads context, so each brief names the files, the commands that must pass, and the exact UI copy. That saves the back-and-forth.
- **Background, not blocking.** Research and scaffolding ran while the main session kept working.
- **Verify the expensive-to-be-wrong facts, trust the rest.** Model IDs and prices were checked against raw docs. Routine things (package versions) are left to `npm install` / `uv add`.
- **Targeted reads.** I extracted only the relevant passages of the docs pages (models, pricing, thinking, caching) instead of loading whole pages.
- **Generated types.** TypeScript event types come from the Pydantic models (`npm run gen:types`), so no model writes them twice and they can't drift. A test enforces this.

### Routing plan for the next milestones (Planned)
- **M1 Hear:** Opus for the audio path (mic capture, Deepgram streaming, speaker labels), where the risk is highest. Sonnet for the transcript UI from the `tenor-ui` spec.
- **M2 to M3:** Opus for the event bus and the claim-check arithmetic. Sonnet for provider adapters and fixtures once the interface is fixed.
- **M4:** Haiku or Sonnet to summarize eval runs and draft labeled utterances for me to review. Opus for the metrics and the classifier-vs-LLM comparison.

---

## 2. Running Tenor: which models, for which job

**The LLM extracts and explains. It never decides a verdict.** Claim verdicts come from data and arithmetic. This rule drives the model choices: Tenor doesn't need a flagship reasoning model, it needs fast, cheap, structured extraction.

| Job | Model | Settings | Why | Status |
|---|---|---|---|---|
| Speech-to-text, both sides, live | Deepgram streaming | interim results, diarization | Documented interim results and speaker diarization, both needed for live labels | Planned (M1) |
| Pull offer terms and claims from each utterance | `gemini-3.5-flash-lite` | thinking `minimal`, JSON schema output | Runs on every caller utterance, on the "flag within 2 s" path. Cheapest, fastest tier: $0.30 / $2.50 per 1M in/out | Planned (M2) |
| Research agent (looks up firm, ticker, register, news via tools) | `gemini-3.8-flash` | thinking `low`, function calling | Needs reliable multi-step tool use. Flash, not Lite | Planned (M3) |
| Pressure-tactic detection | sentence-transformers embeddings + logistic regression (local) | — | No API cost, millisecond latency, works offline, measurable | Planned (M4) |
| Tactic baseline for the eval | `gemini-3.5-flash-lite` zero-shot | — | The honest comparison: is a trained small classifier better than prompting? | Planned (M4) |
| Decision memo after hang-up | `gemini-3.8-flash` | thinking `medium` | One call per session. Quality matters more than speed, but it only explains facts already checked | Planned (M5) |

Model IDs live in `backend/app/config.py` and can be overridden from `.env` (`TENOR_MODEL_FAST`, `TENOR_MODEL_RESEARCH`, `TENOR_MODEL_MEMO`). **Built** in M0.

### Why Gemini through Google AI Studio
- **I already have a billed Google AI Studio key.** One key covers every LLM job, with no new vendor account. The SDK is `google-genai` and reads `GEMINI_API_KEY`.
- **There's a tier for each job.** Flash-Lite for the hot path, Flash for tool use, both with structured output and function calling.
- **Why not the flagship `gemini-4-argon`:** $2 / $10 per 1M tokens (doubling to $4 / $20 on 2026-12-01), paid tier only. It buys deep reasoning, but the LLM in Tenor isn't allowed to reason its way to a verdict. Kept as a one-line config switch for the memo if quality is lacking.
- **Watch item:** `gemini-3.8-flash` doubles to $1.50 / $7.50 on 2027-01-01. Flash-Lite is the fallback for research if that matters.
- **Originally planned:** Claude via the Anthropic SDK. Switched because of the existing key (see `docs/decisions.md`).

Prices, IDs, thinking levels and caching limits were checked on ai.google.dev ([models](https://ai.google.dev/gemini-api/docs/models), [pricing](https://ai.google.dev/gemini-api/docs/pricing), [thinking](https://ai.google.dev/gemini-api/docs/thinking), [caching](https://ai.google.dev/gemini-api/docs/caching)) on 2026-10-20.

### Token and latency budget at runtime (Planned, M2+)
- **Thinking off the hot path.** Thinking tokens are billed as output ($2.50 / 1M on Flash-Lite). Extraction uses `minimal`, Flash-Lite's lowest level and its default.
- **Send the delta, not the transcript.** Each extraction call gets the new utterance plus a compact running offer state, not the whole call so far. Cost stays flat as the call gets longer.
- **Stable prefix first.** Instructions, schema and tool definitions go at the start of every prompt so implicit caching (on by default for Gemini 2.5+) can apply. Honest caveat: the minimum for 3.8 Flash is 4,096 tokens, so the research agent's prompt (tool definitions + call context) is the likely beneficiary. Flash-Lite isn't in Google's minimums table, and the short extraction prompts probably won't cache.
- **Structured output, no retries.** Responses are validated against the same Pydantic models as the events. A malformed response gives a "couldn't verify" state, not a retry loop.
- **Prefetch research.** The research agent starts when a firm or ticker is first named, before the caller makes a claim about it, so the answer is often ready when needed.
- **Log tokens next to latency.** Each LLM stage records input, output and cached tokens from the response's usage data in the same latency log. The eval screen can then show real cost per call, not just this estimate.

**Rough cost of one 15-minute call (estimate, to be replaced with measured numbers in M4).** Assumes ~75 caller utterances × ~800 input / ~150 output tokens for extraction, ~5 research runs × 3 turns × ~3k input / ~500 output tokens, and one memo at ~10k input / ~1.5k output tokens:

| Stage | Input | Output | Cost |
|---|---|---|---|
| Extraction (Flash-Lite) | 60k | 11k | ≈ $0.05 |
| Research (3.8 Flash) | 45k | 7.5k | ≈ $0.06 |
| Memo (3.8 Flash) | 10k | 1.5k | ≈ $0.01 |
| **Total** | | | **≈ $0.12 per call** |

At these prices, model choice matters more for **latency** (2-second flag target) than for cost. That's the real reason the hot path is on Flash-Lite.
