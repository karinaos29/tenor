# Tenor

A live copilot for high-pressure investment sales calls. Put the call on speaker; Tenor listens through the laptop microphone, transcribes both sides, checks the caller's claims against data, flags pressure tactics, suggests what to ask back, and writes a decision memo after the call.

Prototype for the Hiya Voice AI Challenge. No real telephony: microphone input and recorded-call replay only.

> **Status: M3 (Verify).** Live transcript with "You" and "Caller" labels; the offer card fills in as the caller talks; claims are checked against market data ("Doesn't match data", "No evidence found", "Couldn't verify"); the firm is looked up; up to four suggestions (what to say, plus the evidence) and a risk level update live. Milestone write-ups are in [`docs/milestones/`](docs/milestones/); the design is in [`docs/architecture.md`](docs/architecture.md).

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

And against the real Finnhub API (needs `FINNHUB_API_KEY`):

```bash
uv run pytest -m finnhub
```

Market data: real tickers come from Finnhub's free tier; the fictional company in the scam call (Kestrel Motors, KSTL) uses invented test data in `backend/fixtures/companies/`, and firms are looked up in a test register of fictional firms (`backend/fixtures/register.json`). Without a Finnhub key, checks on real tickers show "Couldn't verify".

After changing an event model in `backend/pipeline/events.py`, regenerate the TypeScript types with `npm run gen:types` (frontend/). A backend test fails until you do.

## Docs

- [`docs/architecture.md`](docs/architecture.md): components, events, UI, milestones
- [`CLAUDE.md`](CLAUDE.md): rules and stack
- [`docs/decisions.md`](docs/decisions.md): decisions log (what, why, alternative)
- [`docs/milestones/`](docs/milestones/): one write-up per milestone
- [`ai.md`](ai.md): which AI tools and models were used to build Tenor, and which ones Tenor uses at runtime
