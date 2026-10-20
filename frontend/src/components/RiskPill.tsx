import { useEffect, useState } from "react";
import { useCallStore } from "../stores/call";

const LEVEL = { low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const;

export function RiskPill() {
  const risk = useCallStore((s) => s.risk);
  const level = risk?.level ?? null;
  const [announced, setAnnounced] = useState("");
  useEffect(() => {
    setAnnounced(level ? `Risk level: ${LEVEL[level]}` : "");
  }, [level]);

  if (!risk) return <span className="pill muted">Risk · not scored yet</span>;
  const title = risk.reasons.map((r) => `+${r.points} ${r.label}`).join("; ");
  return (
    <>
      <span className={`pill pill--risk pill--${risk.level}`} title={title || undefined}>
        Risk <span className="numbers">{risk.score}</span> · {LEVEL[risk.level]}
      </span>
      <span className="sr-only" aria-live="polite">{announced}</span>
    </>
  );
}
