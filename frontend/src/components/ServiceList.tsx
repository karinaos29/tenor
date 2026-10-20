import { useHealthStore } from "../stores/health";
import type { ServiceStatus } from "../lib/events.gen";

const SERVICES: { key: keyof ServiceStatus; label: string }[] = [
  { key: "transcription", label: "Transcription" },
  { key: "llm", label: "Call analysis (AI)" },
  { key: "market_data", label: "Market data" },
  { key: "email", label: "Email memo" },
];

export function ServiceList() {
  const { status, services, retryInSec } = useHealthStore();
  const known = status === "connected" && services !== null;

  return (
    <div className="services">
      <div aria-live="polite">
        {status === "offline" && (
          <p className="warn services__server">
            Can&apos;t reach Tenor&apos;s server. Trying again in {retryInSec ?? 1} s.
          </p>
        )}
        {status === "connecting" && <p className="muted services__server">Connecting to Tenor&apos;s server…</p>}
      </div>
      <ul className="services__list">
        {SERVICES.map(({ key, label }) => (
          <li key={key} className="services__item">
            <span>{label}</span>
            {!known ? (
              <span className="muted">{status === "offline" ? "Not checked" : "Checking…"}</span>
            ) : services[key] ? (
              <span className="ok">Ready</span>
            ) : (
              <span className="warn">Key missing</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
