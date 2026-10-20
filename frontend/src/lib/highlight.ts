import type { Offer, Term } from "./events.gen";

export interface Segment {
  text: string;
  mark: boolean;
}

/** Split text into plain and marked parts. Phrases match case-insensitively; overlapping matches
 * are resolved earliest first (longest first on a tie), so marks never nest or repeat. */
export function highlightSegments(text: string, phrases: string[]): Segment[] {
  const lower = text.toLowerCase();
  const found: { start: number; end: number }[] = [];
  for (const phrase of new Set(phrases.map((p) => p.trim().toLowerCase()).filter(Boolean))) {
    let from = 0;
    for (;;) {
      const i = lower.indexOf(phrase, from);
      if (i === -1) break;
      found.push({ start: i, end: i + phrase.length });
      from = i + phrase.length;
    }
  }
  found.sort((a, b) => a.start - b.start || b.end - a.end);
  const picked: { start: number; end: number }[] = [];
  let last = 0;
  for (const m of found) {
    if (m.start < last) continue;
    picked.push(m);
    last = m.end;
  }
  const out: Segment[] = [];
  let pos = 0;
  for (const m of picked) {
    if (m.start > pos) out.push({ text: text.slice(pos, m.start), mark: false });
    out.push({ text: text.slice(m.start, m.end), mark: true });
    pos = m.end;
  }
  if (pos < text.length || out.length === 0) out.push({ text: text.slice(pos), mark: false });
  return out;
}

/** `said` phrases of every offer term (current and replaced) that came from this utterance. */
export function offerPhrasesFor(offer: Offer | null, utteranceId: string): string[] {
  if (!offer) return [];
  const terms: (Term | null)[] = [
    offer.caller_name, offer.firm, offer.instrument, offer.price, offer.quantity,
    offer.total, offer.fees, offer.deadline, offer.payment,
    ...offer.history.flatMap((h) => [h.old, h.new]),
  ];
  return terms.filter((t): t is Term => t !== null && t.utterance_id === utteranceId && t.said.trim() !== "").map((t) => t.said);
}
