import type { TacticFlag } from "./events.gen";

export interface TacticGroup {
  tactic: TacticFlag["tactic"];
  label: string;
  severity: TacticFlag["severity"];
  quote: string;
  count: number;
}

/** One row per tactic: newest quote, strongest severity seen, strong rows first. */
export function groupTactics(flags: TacticFlag[]): TacticGroup[] {
  const map = new Map<string, TacticGroup>();
  for (const f of flags) {
    const g = map.get(f.tactic);
    if (!g) map.set(f.tactic, { tactic: f.tactic, label: f.label, severity: f.severity, quote: f.quote, count: 1 });
    else map.set(f.tactic, { ...g, severity: g.severity === "strong" || f.severity === "strong" ? "strong" : "mild", quote: f.quote, label: f.label, count: g.count + 1 });
  }
  const rank = (g: TacticGroup) => (g.severity === "strong" ? 0 : 1);
  return [...map.values()].sort((a, b) => rank(a) - rank(b)); // stable: keeps first-seen order
}

export function shorten(s: string, n = 90): string {
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}
