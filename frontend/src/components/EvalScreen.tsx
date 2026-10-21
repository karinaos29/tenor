import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { CallResult, DetectorScores, EvalReport, EvalResponse, MetricRow } from "../lib/events.gen";
import { useAppStore } from "../stores/app";
import "./EvalScreen.css";

type Load = { state: "loading" } | { state: "error" } | { state: "done"; report: EvalReport | null };

async function fetchEval(): Promise<EvalResponse> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 4000);
  try {
    const res = await fetch("/api/eval", { signal: ctrl.signal });
    if (!res.ok) throw new Error("bad status");
    return (await res.json()) as EvalResponse;
  } finally {
    clearTimeout(timer);
  }
}

const NO_TACTICS = "No tactics are labeled in this call, so there's nothing to recall; see the risk column";
const f2 = (n: number) => n.toFixed(2);

function Table({ caption, head, children }: { caption: string; head: ReactNode; children: ReactNode }) {
  return (
    <div className="eval__scroll">
      <table className="eval__table">
        <caption className="sr-only">{caption}</caption>
        <thead>{head}</thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `eval-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section className="card eval__section" aria-labelledby={id}>
      <h2 id={id} className="card__title">{title}</h2>
      {children}
    </section>
  );
}

const STATUS = {
  true: { label: "Met", color: "var(--ok)" },
  false: { label: "Not met", color: "var(--danger)" },
  null: { label: "Not measured", color: "var(--muted)" },
} as const;

function Targets({ report }: { report: EvalReport }) {
  return (
    <Section title="Targets">
      <Table
        caption="Targets and what was measured"
        head={<tr><th scope="col">Target</th><th scope="col">Goal</th><th scope="col">Measured</th><th scope="col">Status</th></tr>}
      >
        {report.targets.map((t) => {
          const st = STATUS[String(t.met) as keyof typeof STATUS];
          return (
            <tr key={t.label}>
              <th scope="row">{t.label}</th>
              <td className="numbers">{t.target}</td>
              <td className="numbers">{t.measured}</td>
              <td style={{ color: st.color, fontWeight: 600 }}>{st.label}</td>
            </tr>
          );
        })}
      </Table>
    </Section>
  );
}

function Detectors({ detectors }: { detectors: DetectorScores[] }) {
  const tenor = detectors.find((d) => d.name.startsWith("Tenor"));
  const llm = detectors.find((d) => d.name.includes("LLM"));
  const pair = tenor && llm && tenor !== llm ? [tenor, llm] : null;
  const find = (d: DetectorScores, r: MetricRow): MetricRow | undefined => d.rows.find((x) => x.tactic === r.tactic);
  return (
    <Section title="Pressure-tactic detection (held-out lines)">
      <Table
        caption="Detector comparison"
        head={<tr><th scope="col">Measure</th>{detectors.map((d) => <th key={d.name} scope="col">{d.name}</th>)}</tr>}
      >
        <tr><th scope="row">Precision</th>{detectors.map((d) => <td key={d.name} className="numbers">{f2(d.micro.precision)}</td>)}</tr>
        <tr><th scope="row">Recall</th>{detectors.map((d) => <td key={d.name} className="numbers">{f2(d.micro.recall)}</td>)}</tr>
        <tr><th scope="row">F1</th>{detectors.map((d) => <td key={d.name} className="numbers">{f2(d.micro.f1)}</td>)}</tr>
        <tr><th scope="row">&ldquo;Any tactic&rdquo; F1</th>{detectors.map((d) => <td key={d.name} className="numbers">{f2(d.any_tactic.f1)}</td>)}</tr>
        <tr><th scope="row">Time per line</th>{detectors.map((d) => <td key={d.name} className="numbers">{Math.round(d.latency_ms_median)} ms</td>)}</tr>
      </Table>
      {detectors.map((d) => d.note && <p key={d.name} className="muted eval__note"><strong>{d.name}:</strong> {d.note}</p>)}
      {pair && (
        <Table
          caption="Per-tactic scores"
          head={
            <>
              <tr>
                <th scope="col" rowSpan={2}>Tactic</th>
                <th scope="colgroup" colSpan={2}>{pair[0].name}</th>
                <th scope="colgroup" colSpan={2}>{pair[1].name}</th>
                <th scope="col" rowSpan={2}>Lines</th>
              </tr>
              <tr><th scope="col">P</th><th scope="col">R</th><th scope="col">P</th><th scope="col">R</th></tr>
            </>
          }
        >
          {pair[0].rows.map((r) => {
            const o = find(pair[1], r);
            return (
              <tr key={r.tactic}>
                <th scope="row">{r.label}</th>
                <td className="numbers">{f2(r.precision)}</td>
                <td className="numbers">{f2(r.recall)}</td>
                <td className="numbers">{o ? f2(o.precision) : "—"}</td>
                <td className="numbers">{o ? f2(o.recall) : "—"}</td>
                <td className="numbers">{r.support}</td>
              </tr>
            );
          })}
        </Table>
      )}
    </Section>
  );
}

function Calls({ calls }: { calls: CallResult[] }) {
  return (
    <Section title="Test calls">
      <Table
        caption="Test calls and results"
        head={
          <tr>
            <th scope="col">Call</th><th scope="col">Kind</th><th scope="col">Expected</th><th scope="col">Risk</th>
            <th scope="col">Result</th><th scope="col">False claims caught</th><th scope="col">Tactics P/R</th>
          </tr>
        }
      >
        {calls.map((c) => (
          <tr key={c.name}>
            <th scope="row">{c.name}</th>
            <td>
              {c.kind === "manipulative" ? "Manipulative" : "Honest"}
              {c.hard_honest && <span className="muted eval__tag"> hard case</span>}
            </td>
            <td>{c.expected}</td>
            <td><span className="numbers">{c.risk_score}</span> · {c.risk_level}</td>
            <td style={{ color: c.ok ? "var(--ok)" : "var(--danger)", fontWeight: 600 }}>{c.ok ? "As expected" : "Not as expected"}</td>
            <td className="numbers">{c.false_claims_caught} of {c.false_claims_expected}</td>
            {c.tactic_precision !== null && c.tactic_recall !== null ? (
              <td className="numbers">{`${f2(c.tactic_precision)} / ${f2(c.tactic_recall)}`}</td>
            ) : (
              <td className="numbers" title={NO_TACTICS}>
                <span aria-hidden="true">—</span>
                <span className="sr-only">{NO_TACTICS}</span>
              </td>
            )}
          </tr>
        ))}
      </Table>
    </Section>
  );
}

function Speed({ report }: { report: EvalReport }) {
  return (
    <Section title="Speed per stage">
      {report.latency.length === 0 ? (
        <p className="muted">Speed per stage is measured with audio replays (run_eval.py --audio).</p>
      ) : (
        <Table
          caption="Speed per stage"
          head={<tr><th scope="col">Stage</th><th scope="col">n</th><th scope="col">Median (ms)</th><th scope="col">p95 (ms)</th></tr>}
        >
          {report.latency.map((l) => (
            <tr key={l.stage}>
              <th scope="row">{l.stage}</th>
              <td className="numbers">{l.n}</td>
              <td className="numbers">{Math.round(l.median_ms)}</td>
              <td className="numbers">{Math.round(l.p95_ms)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  );
}

export function EvalScreen() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const setScreen = useAppStore((s) => s.setScreen);

  useEffect(() => {
    let cancelled = false;
    fetchEval().then(
      (r) => !cancelled && setLoad({ state: "done", report: r.report ?? null }),
      () => !cancelled && setLoad({ state: "error" }),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const report = load.state === "done" ? load.report : null;
  return (
    <main className="eval">
      <header className="eval__head">
        <h1 className="eval__title">How Tenor is measured</h1>
        <button className="btn btn--secondary btn--small" onClick={() => setScreen("start")}>Back</button>
      </header>
      {load.state === "loading" && <p className="muted" role="status">Loading the latest evaluation…</p>}
      {load.state === "error" && <p className="warn" role="alert">Couldn&apos;t load the evaluation.</p>}
      {load.state === "done" && !report && (
        <p className="muted">No evaluation has been run yet. Run: uv run python ../eval/run_eval.py (from backend/)</p>
      )}
      {report && (
        <>
          <p className="muted eval__data">{report.data}</p>
          <p className="muted eval__run">
            Run <span className="numbers">{report.run_id}</span> · {new Date(report.created_at).toLocaleDateString()} · commit{" "}
            <span className="numbers">{report.commit}</span> · {report.note}
          </p>
          <Targets report={report} />
          <Detectors detectors={report.detectors} />
          <Calls calls={report.calls} />
          <Speed report={report} />
        </>
      )}
    </main>
  );
}
