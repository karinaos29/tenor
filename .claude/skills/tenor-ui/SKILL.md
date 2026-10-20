---
name: tenor-ui
description: Tenor's visual design system and UI rules. Use for any frontend work on Tenor - new components, layout, styling, copy, states, or animation.
---

# Tenor UI

The user is listening to a phone call, not reading. One glance should say whether something is wrong; a second glance should say what to do.

## Layout (desktop first, min width 1024px; stack below 900px)
- **Call strip** across the top: caller name and firm, listening status and timer, risk pill (always visible).
- **Left column:** live transcript. Caller lines sit left on a `--voice-caller` rule; "You" lines sit right in a `--voice-you-bg` bubble. Lines still being spoken are neutral ("Speaking…", dashed rule, muted italic) until final, because interim speaker labels flip. Lines the user spoke from a suggestion get a small "Suggested by Tenor" tag. Voice colors are used nowhere else.
- **Right rail, ordered by urgency:** Suggestions (max 4) > The offer > Claims vs. data > Pressure tactics.
- **Memo screen** after hang-up; **Start screen** before (consent + mic level check); **Evaluation screen** for reviewers.

## Tokens (define in `frontend/src/styles/tokens.css`, use nowhere else)
Dark only, inspired by Hiya's brand (deep indigo, violet, purple→cyan gradient). Set `color-scheme: dark`.
```css
:root {
  --bg: #0E0B1F; --surface: #17132F; --sunk: #120F27;
  --ink: #F3F1FA; --muted: #A9A3C2; --line: #2C2650;
  --accent: #7346F5;      /* fill: Tenor's suggestions + primary button (white text 5.4:1) */
  --accent-ink: #A08BFF;  /* accent as text on dark surfaces */
  --danger: #FF7B71; --warn: #F2AC45; --ok: #62CC95;   /* severity only */
  --brand-gradient: linear-gradient(90deg, #A07BFF, #22C3EE);  /* brand moments only */
  --bg-wash: radial-gradient(120% 90% at 85% 0%, #3A1A8C 0%, #1B1046 45%, #0E0B1F 80%);
  --font-display: "Plus Jakarta Sans", system-ui, sans-serif;  /* 700/800 */
  --font-body: "Nunito Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
  --voice-caller: #7CC6DA;    /* transcript: caller label + left rule (9.4:1) */
  --voice-you: #D9D3F0;       /* transcript: "You" label */
  --voice-you-bg: #251E4D;    /* transcript: your bubble (ink on it 13.7:1) */
  --voice-you-line: #3A3170;
  --radius-card: 14px; --radius-control: 9px;
}
```
All text tokens are ≥ 6.5:1 on every surface (checked 2026-10-20). Fonts are self-hosted via @fontsource. Never use Hiya's logo or name in the UI.

## Rules
- **One accent.** The violet accent marks Tenor's suggestions (and the one primary button per screen). Red/amber/green mean severity and always come with a text label ("Doesn't match data", "Strong", "Verified"). Never color alone.
- **Max 4 suggestions on screen.** Older ones move to the memo.
- **"Say this" text is the largest body text on screen** (17px+), because the user reads it aloud.
- **Numbers** use `--font-mono` with `font-variant-numeric: tabular-nums`.
- **Gradient only for brand moments:** the Tenor wordmark and the Start screen headline. Never on data, suggestions or severity.
- **Motion only for news:** a new item fades/slides in once (≤250ms). No pulsing, bouncing or looping animation except the small live-recording dot. Respect `prefers-reduced-motion`.
- **No pop-ups, modals or sounds during a call.** Escalation = risk pill turns critical + the related suggestion moves to first place.
- **Every result shows its source and check time** in muted small text.
- **Empty states explain what will appear**, e.g. "Terms fill in as the caller states them."
- **Accessible:** visible focus rings, contrast ≥ 4.5:1 for text, all controls keyboard-reachable, live regions (`aria-live="polite"`) for new suggestions.

## Copy
Plain words, short sentences, written for Eszter.
- "Doesn't match data", not "Claim falsified"
- "No evidence found", not "Not found in index"
- "Couldn't verify", not "Error"
- Suggestions to speak are in quotes and first person: "I don't make decisions on the same day. Can you email me the details first?"
- Never "buy", "sell", "safe" or "scam" as a verdict. Show facts and flags.

## Before you finish any UI task
1. Check contrast on the dark theme (text ≥ 4.5:1).
2. Check 1280px and 900px widths.
3. Check empty, loading ("Prefetching"), ready, and error states.
4. Run `npm run typecheck`.
