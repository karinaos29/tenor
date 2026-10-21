import { useEffect, useId, useRef, useState } from "react";
import { useCallStore } from "../stores/call";

const LEVEL = { low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const;
type Level = keyof typeof LEVEL;

/** Static risk label (no popover), used on the memo. */
export function RiskLabel({ score, level }: { score: number | null; level: Level }) {
  return (
    <span className={`pill pill--risk pill--${level}`}>
      Risk {score !== null && <span className="numbers">{score}</span>}
      {score !== null && " · "}
      {LEVEL[level]}
    </span>
  );
}

export function RiskPill() {
  const risk = useCallStore((s) => s.risk);
  const level = risk?.level ?? null;
  const [announced, setAnnounced] = useState("");
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    setAnnounced(level ? `Risk level: ${LEVEL[level]}` : "");
  }, [level]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!risk) return <span className="pill muted">Risk · not scored yet</span>;
  return (
    <span className="riskpop" ref={wrap}>
      <button
        ref={btn}
        type="button"
        className={`pill pill--risk pill--${risk.level}`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        Risk <span className="numbers">{risk.score}</span> · {LEVEL[risk.level]}
      </button>
      {open && (
        <div id={panelId} className="riskpop__panel" role="group" aria-label="Why the risk is this level">
          <p className="riskpop__title">Why the risk is {LEVEL[risk.level].toLowerCase()}</p>
          {risk.reasons.length === 0 ? (
            <p>Nothing has raised the risk yet.</p>
          ) : (
            <ul className="riskpop__list">
              {risk.reasons.map((r, i) => (
                <li key={i}>
                  <span className="numbers">+{r.points}</span> {r.label}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <span className="sr-only" aria-live="polite">{announced}</span>
    </span>
  );
}
