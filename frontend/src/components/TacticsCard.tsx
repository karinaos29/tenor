import { groupTactics, shorten } from "../lib/tactics";
import { useCallStore } from "../stores/call";

const SEVERITY = {
  strong: { label: "Strong", color: "var(--danger)" },
  mild: { label: "Mild", color: "var(--warn)" },
} as const;

export function TacticsCard() {
  const tactics = useCallStore((s) => s.tactics);
  const groups = groupTactics(tactics);
  if (groups.length === 0) return <p className="muted">Pressure tactics, like a deadline for today, are flagged here.</p>;
  return (
    <ul className="tactics">
      {groups.map((g) => (
        <li key={g.tactic} className="tactics__row">
          <p className="tactics__head">
            <span className="tactics__label">{g.label}</span>
            <span className="tactics__sev" style={{ color: SEVERITY[g.severity].color }}>{SEVERITY[g.severity].label}</span>
            {g.count > 1 && <span className="muted tactics__count">{g.count} times</span>}
          </p>
          <p className="muted tactics__quote">&ldquo;{shorten(g.quote)}&rdquo;</p>
        </li>
      ))}
    </ul>
  );
}
