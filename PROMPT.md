# Kickoff prompt for Claude Code

Paste the block below into Claude Code from the repo root, after copying in
CLAUDE.md, .claude/skills/ and docs/architecture.md.

---

You're helping me build Tenor, a prototype for a voice AI internship challenge. Read `CLAUDE.md` and `docs/architecture.md` first; they're the source of truth for scope, stack, components, events, UI and milestones.

**Goal:** a polished, end-to-end web prototype. The user puts a phone call on speaker; the browser captures the laptop microphone; the backend transcribes both sides, extracts the offer and claims, checks claims against data, flags pressure tactics, ranks up to 4 suggestions (research results and "say this" lines), and writes a decision memo after the call. Reviewers will judge the end-to-end experience, the UI, the architecture, and the visible milestones and reasoning.

**Out of scope:** real phone integration (Twilio, softphones), user accounts, deployment. Mention telephony only as a future audio source behind the existing interface.

**Non-negotiables:**
- Components communicate only through the typed async event bus.
- The LLM never decides a verdict; numbers and verdicts come from data and arithmetic.
- Every result shows its source; missing data says "couldn't verify".
- Fictional companies for scam scenarios; real tickers only for honest ones.
- Live mic and recorded replay run through the identical pipeline.
- UI follows the `tenor-ui` skill exactly.

**How we'll work:**
1. Today, set up the repo skeleton only: the folder layout from `CLAUDE.md`, `pyproject.toml` with uv, a Vite React TS app, `tokens.css` from the `tenor-ui` skill, `.env.example` (DEEPGRAM_API_KEY, ANTHROPIC_API_KEY, FINNHUB_API_KEY, RESEND_API_KEY), an empty `docs/decisions.md`, a health-check WebSocket between frontend and backend, and a README stub with run commands. Commit as `m0: skeleton`.
2. Then we'll run `/tenor-milestone m1`, and one milestone per session after that. Never start the next milestone without my go-ahead.

Before writing any code, enter plan mode and give me:
- the skeleton file tree,
- any questions where `docs/architecture.md` is ambiguous or where you'd recommend a different choice (with the reason),
- the risks you see for M1 (mic capture, Deepgram streaming, speaker labeling).

Keep explanations short. Ask me when something is a judgment call; decide yourself when it's routine and note it in `docs/decisions.md`.
