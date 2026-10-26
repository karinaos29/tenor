# AI in Tenor

Two questions: which AI I used to **build** Tenor, and which models Tenor **runs** on. The rule for both: put each task on the cheapest model that does it reliably.

## Building Tenor
I built Tenor with **Claude Code**, routing each kind of work to a model and effort level:

| Work | Model | Effort |
|---|---|---|
| Architecture, event contracts, pipeline core, verdict logic, guards, reviews | Claude Opus 5.5 (main session) | default |
| Frontend screens, from written specs | Claude Sonnet 5.5 (subagents) | medium |
| Test suites, told to report bugs rather than patch around them | Claude Sonnet 5.5 (subagents) | medium |
| Classifier training lines | Claude Sonnet 5.5 (subagent) | medium |
| Held-out test lines and test calls, with no access to the training data | Claude Haiku 5.5 (subagent) | medium |
| Docs research (model IDs, APIs), first drafts | Claude Haiku 5.5 (subagents) | low |
| Format conversion, exact-string checks, test voices | no model: `pandoc`, `curl` + `grep`, `say` | — |

In total that was 13 Sonnet runs (~1.1M tokens) and 4 Haiku runs (~0.3M tokens); everything else ran on Opus.

What made this work:
- **Durable context.** `CLAUDE.md` and two project skills hold the rules, so no session needed them re-explained.
- **Cross-model review.** Opus reviewed Sonnet's code, and Sonnet's independent tests found real bugs in Opus's.
- **Tools before models.** A converter, `grep` and `curl` cost no tokens and don't guess.

## Running Tenor
**The LLM extracts and explains; it never decides.** So Tenor doesn't need a flagship model. It needs fast, cheap, checkable output, and nothing on the hot path waits for an LLM.

| Job | Model | Thinking |
|---|---|---|
| Speech-to-text, both sides | Deepgram Nova-3 streaming, with diarization | — |
| Offer terms, claims, verdicts, risk; speaker labels on replays | no model: rules and arithmetic | — |
| Fuzzy extraction ("signed a deal") | `gemini-3.5-flash-lite` + `gemini-3.1-flash-lite`, hedged | minimal |
| Plain-words research summaries | same, hedged, under a number guard | minimal |
| Pressure tactics | `all-MiniLM-L6-v2` + logistic regression, local (~9 ms per line) | — |
| Who is "You" on a live call | `microsoft/wavlm-base-plus-sv` voice prints, local (~0.17 s per segment) | — |
| Memo summary | `gemini-3.8-flash` + both flash-lite models, hedged, under number and word guards | low / minimal |
| Test-call voices (development only) | `gemini-3.8-flash-tts`, macOS `say` as fallback | — |

**Hedged** means each request goes to every listed model at once, and the first valid answer wins. Gemini's latency per model swung from under 1 s to 30 s within a day.

**Why Gemini via Google AI Studio:** I already had a billed key, so one key covers every LLM job. Model IDs live in `backend/app/config.py` and can be overridden from `.env`.
