# Tenor

Tenor is a live copilot for high-pressure investment sales calls. The user puts a phone call on speaker; Tenor listens through the laptop microphone, transcribes both sides, checks the caller's claims against data, flags pressure tactics, suggests what to ask back, and sends a decision memo after the call.

This is a prototype for the Hiya Voice AI Challenge (summer internship take-home). Reviewers care about: a polished end-to-end prototype, a clear architecture, visible milestones, and the reasoning behind decisions. No real telephony: microphone input (and recorded-call replay) only.

Full design: `docs/architecture.md`. Read it before any structural change.

## Persona
Eszter, 58, retired teacher with savings. Polite, not a finance expert. Design every screen and string for her: plain words, calm by default, glanceable.

## Stack
- Backend: Python 3.12, FastAPI, asyncio, Pydantic v2, uv for dependencies
- STT: Deepgram streaming (interim results, diarization)
- LLM: Google Gemini via the `google-genai` SDK and a Google AI Studio key. Extraction and research wording are hedged across `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` (first valid answer wins); research is data first, and the LLM only rewords under a number guard. `gemini-3.8-flash` is planned for the memo. See `ai.md`.
- Market data: `MarketDataProvider` interface with `FinnhubProvider` (real tickers) and `FixtureProvider` (fictional companies in `backend/fixtures/`)
- Classifier: sentence-transformers embeddings + scikit-learn logistic regression
- Frontend: React + TypeScript + Vite, Zustand, Framer Motion (restrained)
- Storage: in-memory session, SQLite for saved calls and eval runs
- Email: Resend

## Repository layout
```
backend/
  app/            FastAPI app, WebSocket endpoints
  audio/          audio sources (mic stream, file replay)
  pipeline/       event bus + one module per component
  providers/      market data, registers, news adapters
  detector/       tactic taxonomy, training, inference
  memo/           memo writer + email
  fixtures/       fictional companies, firms, scripted calls
  tests/
frontend/src/
  components/  stores/  lib/  styles/
eval/             test set, scripts, results
docs/             architecture.md, decisions.md, milestones/
```

## Rules
- Components talk only through the event bus (`backend/pipeline/bus.py`). No direct calls between components.
- Every event is a Pydantic model with a timestamp. Generate TypeScript types from the models; never hand-write duplicate types.
- The LLM extracts and explains; it never decides a verdict. Claim verdicts come from data and arithmetic.
- Every result carries a source and a check time. Missing data = "couldn't verify", never a guess.
- Every external call has a timeout and a fallback state.
- Fictional companies only for scam scenarios. Never make claims about real firms.
- Tenor never says buy or sell.
- Log the latency of every stage; the eval screen reads these logs.
- Secrets live in `.env` (see `.env.example`); never commit keys. Model IDs live in `backend/app/config.py` (overridable from `.env`), never hard-coded in components.

## Commands
- Backend: `uv run uvicorn app.main:app --reload` (from `backend/`)
- Frontend: `npm run dev` (from `frontend/`)
- Tests: `uv run pytest`, `npm run test`, `npm run typecheck`
- Replay a call: `uv run python -m audio.replay fixtures/calls/scam_kstl.wav`

## Working style
- Work one milestone at a time (see `docs/architecture.md` > Milestones). Use the `tenor-milestone` skill.
- For any UI work, use the `tenor-ui` skill.
- Record each non-obvious decision in `docs/decisions.md` (date, decision, why, alternative).
