# Demo video script (≈ 3 min)

First person, plain and calm, about 140 words per minute. Times are video time. The scam call runs 2:14 in real time, so record it at real pace and cut between the moments below.

| # | Time | On screen | Narration |
|---|---|---|---|
| 1 | 0:00–0:15 | Title card, then the Start screen | "Some people lose their savings to a friendly phone call that turns into pressure. Tenor sits next to the phone and listens with you." |
| 2 | 0:15–0:35 | Start screen: consent box, **Check microphone** (the level bar moves), services "Ready". Press **Replay a test call** → **Pushy share offer** | "Before a call, Tenor checks the microphone and its services. For this demo I'll replay a recorded test call: a pushy share offer. It goes through exactly the same pipeline as a live call." |
| 3 | 0:35–1:40 | Live screen. Transcript (Caller on the left, You on the right). The offer card fills: KSTL, $0.42, "10,000 shares (was 5,000)". At call time 0:39, "up 40% this quarter" gets **Doesn't match data** within about a second; the claims card shows +40% vs −12.5%. The first suggestion: "That's not what I see…". "Hartwell & Crane is not in the register". Pressure tactics appear (Rushing you, Keeping it secret, Promises no risk). The risk pill climbs to **Critical**; open it to show the reasons | "The offer card fills in as the caller talks, and notices when the amount goes up. Here's the claim that matters: forty percent this quarter. Tenor checks the market data, which says the stock fell twelve and a half percent, and marks it in under a second. Then it suggests what I could say back. The firm isn't in the register. Each pressure tactic is flagged as it's spoken, and the risk climbs to critical. Every result says where it came from." |
| 4 | 1:40–2:10 | The call ends → **Read your memo**. Headline, summary, sections. Click **at 0:39** on the claim → the transcript opens at that line. Email card → **Send** → "Sent to …" | "When the call ends, the memo is ready in about a second. What was offered, what didn't match, the pressure, questions to ask, and steps that can help. Each item links back to its moment in the call. The facts come from data; Gemini only words the summary, and it's checked before it's used. I can email it to myself or to family." |
| 5 | 2:10–2:25 | **New call** → replay **Bank adviser, index fund** (cut to the end) | "Now the contrast: a bank adviser and a real index fund. The risk stays low, the bank is registered, and a real deadline said calmly isn't treated as pressure." |
| 6 | 2:25–2:50 | Start screen → **For reviewers: how Tenor is measured**. Targets table, then classifier vs. Gemini | "This is how Tenor is measured. On lines written by a different AI model than the training data, precision is 0.84 and recall 0.85. None of the seven honest calls is rated high, and a claim becomes a verdict in about 0.7 seconds. Honestly, Gemini zero-shot scores higher, 0.92 against 0.84, but it's about 75 times slower and rate-limited, so the local model runs live." |
| 7 | 2:50–3:05 | Architecture diagram (`docs/img/system-overview.png`) | "One event bus connects every part. Data and arithmetic decide every verdict; the language model only extracts and explains. Next: real telephony behind the same audio interface, and the model as a second opinion in the background." |

**Optional live take (replaces scene 2–3):** read the Silverline dialogue (`backend/fixtures/calls/scripts/scam_silverline.txt`) aloud with someone else playing the caller on a phone on speaker, and press **Start listening**. Tenor should flag the Apple claim against Apple's real data and the tactics as they're spoken. Keep the replay take as a backup.

## Recording checklist
- Window 1280×800, dark theme, 100% zoom; hide the bookmarks bar and notifications.
- Hide `.env`, terminals and API keys. Close other tabs.
- Backend: `uv run uvicorn app.main:app --reload` (from `backend/`). Frontend: `npm run dev` (from `frontend/`). Open http://localhost:5173.
- All services show "Ready" before recording (keys in `.env`); the honest call needs the Finnhub key for real VOO data.
- Don't edit backend files while recording: `--reload` restarts the server and drops the call.
- Run `uv run python ../eval/run_eval.py --audio --live-data` beforehand so the evaluation screen shows the latest run.
- One take per scene; keep the cursor still while narrating.
