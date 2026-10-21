---
name: tenor-milestone
description: Workflow for building one Tenor milestone (M1-M5) from plan to tagged commit. Use when starting, continuing or finishing a milestone.
argument-hint: [m1|m2|m3|m4|m5]
disable-model-invocation: true
---

# Build milestone $ARGUMENTS

Milestones (see `docs/milestones.md`):
- **m1 Hear:** mic capture in the browser, audio WebSocket gateway, Deepgram streaming, caller/user labels, live transcript UI. Demo: transcript appears live.
- **m2 Understand:** event bus, entity extraction, offer tracker with change detection, file replay source, the two scripted test calls. Demo: offer card fills live.
- **m3 Verify:** fast-lane claim checks, provider adapters + fixtures, research agent with prefetch, suggestion engine (rank, cap 4, expire), risk score. Demo: false claim flagged within 2 s.
- **m4 Detect:** tactic taxonomy, labeled utterances, classifier vs. LLM zero-shot baseline, full test set, evaluation screen. Demo: metrics table on screen.
- **m5 Deliver:** memo writer + email, UI polish pass, README, demo video script. Demo: full call end to end.

## Steps
1. **Read** `CLAUDE.md`, `docs/architecture.md` and `docs/decisions.md`. Check what earlier milestones left in place.
2. **Plan** in plan mode: list files to create or change, events added, tests, and the acceptance criteria below. Wait for approval.
3. **Build** in small steps. After each step run the relevant tests. Keep everything working end to end; never leave the app broken between steps.
4. **UI work** follows the `tenor-ui` skill.
5. **Verify** against the acceptance criteria. Run `uv run pytest`, `npm run test`, `npm run typecheck`. Replay `fixtures/calls/` through the pipeline where relevant and report measured latencies.
6. **Document:**
   - Add decisions to `docs/decisions.md`.
   - Add a row for $ARGUMENTS to `docs/milestones.md` (what it added, the key measurement) and a line under "What real runs caught".
7. **Commit** with message `$ARGUMENTS: <summary>` and tag `$ARGUMENTS`. Ask before pushing.
8. **Stop.** Summarize in 5 lines and wait. Don't start the next milestone.

## Acceptance criteria (every milestone)
- The app starts with the two documented commands and works with no manual steps.
- Tests pass; no type errors.
- Every new external call has a timeout and a fallback state shown in the UI.
- Latency for new stages is logged.
- The milestone demo works on the replay call, not only on live mic.
