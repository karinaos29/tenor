import { CLAIM_STATUS, claimLine, dataLine, sortedChecked } from "../lib/claimText";
import { useCallStore } from "../stores/call";

/** Split text so numbers render in the mono face. */
function withNumbers(text: string) {
  return text.split(/(-?\+?\$?\d[\d,.]*%?)/g).map((p, i) =>
    i % 2 === 1 ? <span key={i} className="numbers">{p}</span> : <span key={i}>{p}</span>,
  );
}

export function ClaimsCard() {
  const claims = useCallStore((s) => s.claims);
  const rows = sortedChecked(claims);
  if (rows.length === 0) return <p className="muted">Claims the caller makes are checked against market data here.</p>;
  return (
    <ul className="claims">
      {rows.map((c) => {
        if (c.status === "checking") return null;
        const st = CLAIM_STATUS[c.status];
        const data = dataLine(c);
        return (
          <li key={c.id} className="claims__row">
            <p className="claims__claim">{withNumbers(claimLine(c))}</p>
            {data && <p className="claims__data">{withNumbers(data)}</p>}
            <p className="claims__status" style={{ color: st.color }}>{st.label}</p>
            {c.source && c.checked_in_ms !== null && (
              <p className="claims__src">Source: {c.source} · checked in {Math.round(c.checked_in_ms)} ms</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
