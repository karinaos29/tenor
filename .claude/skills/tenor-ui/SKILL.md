---
name: tenor-ui
description: Tenor's visual design system and UI rules. Use for any frontend work on Tenor - new components, layout, styling, copy, states, or animation.
---

# Tenor UI

The user is listening to a phone call, not reading. One glance should say whether something is wrong; a second glance should say what to do.

## Layout (desktop first, min width 1024px; stack below 900px)
- **Call strip** across the top: caller name and firm, listening status and timer, risk pill (always visible).
- **Left column:** live transcript. Caller lines in ink, user lines labeled "You". Lines the user spoke from a suggestion get a small "Suggested by Tenor" tag.
- **Right rail, ordered by urgency:** Suggestions (max 4) > The offer > Claims vs. data > Pressure tactics.
- **Memo screen** after hang-up; **Start screen** before (consent + mic level check); **Evaluation screen** for reviewers.

## Tokens (define in `frontend/src/styles/tokens.css`, use nowhere else)
```css
:root {
  --bg: #EEF0EC; --surface: #FFFFFF; --sunk: #F6F7F4;
  --ink: #14181E; --muted: #5C6470; --line: #D9DDD6;
  --accent: #2E47B0;                 /* Tenor's own suggestions only */
  --danger: #B3261E; --warn: #A35F00; --ok: #1E7349;  /* severity only */
  --font-display: "Bricolage Grotesque", system-ui, sans-serif;
  --font-body: "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
  --radius-card: 14px; --radius-control: 9px;
}
/* Dark theme: --bg #0F1216, --surface #171B21, --sunk #12161B, --ink #E6E9ED,
   --muted #99A1AB, --line #2A3038, --accent #93A6FF, --danger #FF7B71,
   --warn #F2AC45, --ok #62CC95. Apply via prefers-color-scheme. */
```

## Rules
- **One accent.** The accent marks Tenor's suggestions. Red/amber/green mean severity and always come with a text label ("Doesn't match data", "Strong", "Verified"). Never color alone.
- **Max 4 suggestions on screen.** Older ones move to the memo.
- **"Say this" text is the largest body text on screen** (17px+), because the user reads it aloud.
- **Numbers** use `--font-mono` with `font-variant-numeric: tabular-nums`.
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
1. Check light and dark theme.
2. Check 1280px and 900px widths.
3. Check empty, loading ("Prefetching"), ready, and error states.
4. Run `npm run typecheck`.
