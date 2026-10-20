import { useHealthStore } from "../stores/health";
import type { ServiceStatus } from "../lib/events.gen";
import "./ConnectionCard.css";

const SERVICES: { key: keyof ServiceStatus; label: string }[] = [
  { key: "transcription", label: "Transcription" },
  { key: "llm", label: "Call analysis (AI)" },
  { key: "market_data", label: "Market data" },
  { key: "email", label: "Email memo" },
];

function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

export function ConnectionCard() {
  const { status, rttMs, services, lastCheckedAt, retryInSec } = useHealthStore();

  let label: string;
  let tone: string;
  if (status === "connected") {
    label = "Connected";
    tone = "ok";
  } else if (status === "offline") {
    label = `Can't reach Tenor's server. Trying again in ${retryInSec ?? 1} s.`;
    tone = "warn";
  } else {
    label = "Connecting…";
    tone = "muted";
  }

  return (
    <main className="connection">
      <header className="connection__head">
        <h1 className="connection__wordmark">Tenor</h1>
        <p className="connection__tagline">
          Listens to investment calls with you and checks what the caller says.
        </p>
      </header>

      <section className="card" aria-labelledby="connection-title">
        <h2 id="connection-title" className="card__title">Connection</h2>

        <div aria-live="polite" className="card__status">
          <p className={`status status--${tone}`}>{label}</p>
          {status === "connected" && rttMs !== null && (
            <p className="rtt">
              <span className="rtt__label">Response time</span>{" "}
              <span className="numbers rtt__value">{rttMs} ms</span>
            </p>
          )}
        </div>

        <ul className="services">
          {SERVICES.map(({ key, label: name }) => {
            const known = status === "connected" && services !== null;
            const ready = known && services[key] === true;
            return (
              <li key={key} className="services__item">
                <span>{name}</span>
                {!known ? (
                  <span className="services__state services__state--muted">
                    {status === "offline" ? "Not checked" : "Checking…"}
                  </span>
                ) : ready ? (
                  <span className="services__state services__state--ok">Ready</span>
                ) : (
                  <span className="services__state services__state--warn">Key missing</span>
                )}
              </li>
            );
          })}
        </ul>

        {lastCheckedAt !== null && (
          <p className="card__checked">Checked at {formatTime(lastCheckedAt)}</p>
        )}
      </section>
    </main>
  );
}
