# Tenor

A live copilot for high-pressure investment sales calls. Put the call on speaker; Tenor listens through the laptop microphone, transcribes both sides, checks the caller's claims against data, flags pressure tactics, suggests what to ask back, and writes a decision memo after the call.

Prototype for the Hiya Voice AI Challenge. No real telephony: microphone input and recorded-call replay only.

> **Status: M0 (skeleton).** The backend and frontend run and talk over a health-check WebSocket. Milestones M1–M5 are in [`docs/milestones/`](docs/milestones/).

## Run

Requires Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 22+.

```bash
cp .env.example .env    # add keys; all optional for M0
```

Backend (from `backend/`):

```bash
uv run uvicorn app.main:app --reload
```

Frontend (from `frontend/`, first time `npm install`):

```bash
npm run dev
```

Open http://localhost:5173. The Connection card shows whether the backend is reachable, the round-trip time, and which API keys are set.

## Test

```bash
uv run pytest          # backend/
npm run test           # frontend/
npm run typecheck      # frontend/
```

After changing an event model in `backend/pipeline/events.py`, regenerate the TypeScript types with `npm run gen:types` (frontend/). A backend test fails until you do.

## Docs

- [`CLAUDE.md`](CLAUDE.md): rules and stack
- [`docs/decisions.md`](docs/decisions.md): decisions log (what, why, alternative)
- [`docs/milestones/`](docs/milestones/): one write-up per milestone
- [`ai.md`](ai.md): which AI tools and models were used to build Tenor, and which ones Tenor uses at runtime
