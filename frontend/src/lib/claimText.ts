import type { Claim } from "./events.gen";

export const CLAIM_STATUS: Record<Exclude<Claim["status"], "checking">, { label: string; color: string }> = {
  false: { label: "Doesn't match data", color: "var(--danger)" },
  verified: { label: "Matches data", color: "var(--ok)" },
  not_found: { label: "No evidence found", color: "var(--warn)" },
  unverifiable: { label: "Couldn't verify", color: "var(--muted)" },
};

const sign = (n: number) => (n > 0 ? "+" : "");

function truncate(s: string, n = 70): string {
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}

/** The claim in plain words. */
export function claimLine(c: Claim): string {
  const v = c.claimed_value;
  if ((c.metric === "price_change" || c.metric === "return") && v !== null) {
    return `Claimed: ${sign(v)}${v}% ${c.period ?? ""}`.trim();
  }
  if (c.metric === "guarantee") {
    return `Claimed: guaranteed${v ? ` +${v}%` : ""}${c.period ? " " + c.period : ""}`;
  }
  if (c.metric === "price" && v !== null) return `Offered: $${v} a share`;
  return `Claimed: “${truncate(c.text)}”`;
}

/** What the data says, or null. */
export function dataLine(c: Claim): string | null {
  if (c.actual_value !== null) {
    const a = c.actual_value;
    if (c.metric === "price") return `Market: $${a} a share`;
    return `Data: ${sign(a)}${a}${c.unit === "%" ? "%" : ""}${c.note ? ` (${c.note})` : ""}`;
  }
  return c.note;
}

const rank = (c: Claim) => (c.status === "false" ? 0 : c.status === "not_found" ? 1 : 2);

/** Checked claims only; false first, then not found, then the rest (stable). */
export function sortedChecked(claims: Claim[]): Claim[] {
  return claims
    .filter((c) => c.status !== "checking")
    .map((c, i) => [c, i] as const)
    .sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1])
    .map(([c]) => c);
}
