# Tenor

A live copilot for high-pressure investment sales calls. Put the call on speaker; Tenor listens through the laptop microphone, transcribes both sides, checks the caller's claims against data, flags pressure tactics, suggests what to ask back, and writes a decision memo after the call.

Prototype for the Hiya Voice AI Challenge. No real telephony: microphone input and recorded-call replay only.

> **Status: M2 (Understand).** Live transcript with "You" and "Caller" labels, plus the offer card (who's calling, what, price, quantity, total, deadline, payment) filling in live, with changed terms marked. Milestone write-ups are in [`docs/milestones/`](docs/milestones/); the design is in [`docs/architecture.md`](docs/architecture.md).

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

Open http://localhost:5173. The Start screen shows which services are ready. Press **Replay a test call** to watch a recorded call transcribe live, or tick the consent box, check the microphone, and press **Start listening** with a phone call on speaker.

Replay a recorded call without the browser (same pipeline, prints the transcript and latencies), from `backend/`:

```bash
uv run python -m audio.replay fixtures/calls/scam_kstl.wav
```

Test calls live in `backend/fixtures/calls/`: `scam_kstl` (pushy, fictional firm and stock), `honest_voo` (bank adviser, real index fund), `m1_hello` (36 s). Scripts are plain text in `scripts/`; the expected offer and claims are in `expected/`. To re-voice the calls after editing a script (Gemini TTS, needs `GEMINI_API_KEY`), from `backend/`:

```bash
uv run python fixtures/calls/make_calls.py
```

## Test

```bash
uv run pytest          # backend/
npm run test           # frontend/
npm run typecheck      # frontend/
```

Opt-in test against the real Deepgram API (needs `DEEPGRAM_API_KEY`, takes ~40 s), from `backend/`:

```bash
uv run pytest -m deepgram
```

After changing an event model in `backend/pipeline/events.py`, regenerate the TypeScript types with `npm run gen:types` (frontend/). A backend test fails until you do.

## Docs

- [`docs/architecture.md`](docs/architecture.md): components, events, UI, milestones
- [`CLAUDE.md`](CLAUDE.md): rules and stack
- [`docs/decisions.md`](docs/decisions.md): decisions log (what, why, alternative)
- [`docs/milestones/`](docs/milestones/): one write-up per milestone
- [`ai.md`](ai.md): which AI tools and models were used to build Tenor, and which ones Tenor uses at runtime
