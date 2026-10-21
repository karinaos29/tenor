import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { newCall } from "../lib/callSession";
import { formatClock } from "../lib/callState";
import type { CallMemoResponse, EmailDefaults, EmailResult, Memo, MemoItem, Utterance } from "../lib/events.gen";
import { useAppStore } from "../stores/app";
import { useCallStore } from "../stores/call";
import { RiskLabel } from "./RiskPill";
import "./LiveScreen.css";
import "./MemoScreen.css";

export const POLL_MS = 1000;
export const POLL_MAX = 90;
const FAILED_TEXT = "Couldn't write the memo. The call was saved; try again in a moment.";

async function getJson<T>(url: string, init?: RequestInit, timeoutMs = 4000): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

type Load = { state: "writing" } | { state: "failed" } | { state: "ready"; memo: Memo };

function useMemoLoad(callId: string | null): { load: Load; retry: () => void } {
  const [load, setLoad] = useState<Load>({ state: "writing" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!callId) {
      setLoad({ state: "failed" });
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ticks = 0;
    setLoad({ state: "writing" });
    const tick = async () => {
      const body = await getJson<CallMemoResponse>(`/api/calls/${encodeURIComponent(callId)}/memo`);
      if (cancelled) return;
      if (body?.status === "ready" && body.memo) return setLoad({ state: "ready", memo: body.memo });
      if (body?.status === "failed") return setLoad({ state: "failed" });
      ticks += 1;
      if (ticks >= POLL_MAX) return setLoad({ state: "failed" });
      timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [callId, attempt]);
  return { load, retry: () => setAttempt((a) => a + 1) };
}

const sourceText = (s: Memo["source"]) => (s === "replay" ? "Replay" : "Microphone");

function Item({ item, onJump }: { item: MemoItem; onJump: (t: number) => void }) {
  return (
    <li className={`memo__item memo__item--${item.tone}`}>
      <p className="memo__text">
        {item.text}
        {item.t !== null && (
          <button className="memo__at numbers" onClick={() => onJump(item.t as number)}>
            at {formatClock(item.t * 1000)}
          </button>
        )}
      </p>
      {item.detail && <p className="memo__detail">{item.detail}</p>}
      {item.source && <p className="memo__src">{item.source}</p>}
    </li>
  );
}

function TranscriptLine({ u, mark }: { u: Utterance; mark: boolean }) {
  return (
    <div id={`memo-line-${u.id}`} className={`memo__line${mark ? " memo__line--mark" : ""}`} data-marked={mark ? "true" : undefined}>
      <div className={`line line--${u.speaker}`}>
        <p className="line__meta">
          <span className="line__who">{u.speaker === "user" ? "You" : "Caller"}</span>
          <span className="line__time numbers">{formatClock(u.t_start * 1000)}</span>
        </p>
        <p className="line__text">{u.text}</p>
      </div>
    </div>
  );
}

function EmailCard({ callId }: { callId: string }) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [to, setTo] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<EmailResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getJson<EmailDefaults>("/api/email").then((d) => {
      if (cancelled) return;
      setConfigured(d?.configured === true);
      if (d?.to) setTo((cur) => cur || (d.to as string));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (sending || !configured || !to.trim()) return;
    setSending(true);
    setResult(null);
    const body = await getJson<EmailResult>(
      `/api/calls/${encodeURIComponent(callId)}/email`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ to: to.trim() }) },
      15000,
    );
    setResult(body ?? { ok: false, message: "Couldn't send the email. Try again in a moment." });
    setSending(false);
  };

  return (
    <section className="card memo__email" aria-labelledby="memo-email-title">
      <h2 id="memo-email-title" className="card__title">Email this memo</h2>
      <form className="memo__form" onSubmit={onSubmit} style={{ marginTop: 12 }}>
        <div className="memo__field">
          <label htmlFor="memo-email">Email address</label>
          <input id="memo-email" type="email" autoComplete="email" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <button className="btn" type="submit" disabled={sending || configured !== true}>
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
      {configured === false && (
        <p className="muted memo__result">Email isn&apos;t set up yet (no Resend key). You can still print the memo.</p>
      )}
      <div aria-live="polite">
        {result && (
          <p className="memo__result" style={{ color: result.ok ? "var(--ok)" : "var(--warn)" }}>{result.message}</p>
        )}
      </div>
    </section>
  );
}

function MemoView({ memo }: { memo: Memo }) {
  const [open, setOpen] = useState(false);
  const [mark, setMark] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const jump = useCallback(
    (t: number) => {
      const lines = memo.transcript;
      if (lines.length === 0) return;
      let target = lines[0];
      for (const u of lines) if (u.t_start <= t) target = u;
      setOpen(true);
      setPending(target.id);
    },
    [memo.transcript],
  );

  useEffect(() => {
    if (!pending) return;
    setMark(pending);
    setPending(null);
    const el = document.getElementById(`memo-line-${pending}`);
    if (el && typeof el.scrollIntoView === "function") {
      const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    }
    const id = setTimeout(() => setMark(null), 3000);
    return () => clearTimeout(id);
  }, [pending]);

  return (
    <>
      <header className="memo__top">
        <p className="memo__eyebrow">Your call memo</p>
        <div className="memo__meta">
          <span>{new Date(memo.started_at).toLocaleString()}</span>
          <span className="numbers">{formatClock(memo.duration_s * 1000)}</span>
          <span>{sourceText(memo.source)}</span>
        </div>
        {memo.risk_level ? <RiskLabel score={memo.risk_score} level={memo.risk_level} /> : <span className="muted">Risk · not scored</span>}
      </header>
      <h1 className="memo__title">{memo.headline}</h1>
      <p className="memo__summary">{memo.summary}</p>
      <p className="muted memo__wording">
        {memo.summary_wording === "gemini" ? "Summary worded by Gemini from the facts below" : "Summary built from the facts below"}
      </p>

      {memo.sections.map((s) => (
        <section key={s.id} className="card memo__section" aria-labelledby={`memo-sec-${s.id}`}>
          <h2 id={`memo-sec-${s.id}`} className="card__title">{s.title}</h2>
          {s.items.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>{s.empty}</p>
          ) : (
            <ul className="memo__items">
              {s.items.map((it, i) => (
                <Item key={i} item={it} onJump={jump} />
              ))}
            </ul>
          )}
        </section>
      ))}

      <section className="card memo__section" aria-labelledby="memo-transcript">
        <div className="memo__thead">
          <h2 id="memo-transcript" className="card__title">Full transcript</h2>
          <button
            className="btn btn--secondary btn--small memo__toggle"
            aria-expanded={open}
            aria-controls="memo-transcript-body"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Hide the full transcript" : "Show the full transcript"}
          </button>
        </div>
        <div id="memo-transcript-body" className="memo__tbody" hidden={!open}>
          {memo.transcript.length === 0 ? (
            <p className="muted">No words were transcribed in this call.</p>
          ) : (
            memo.transcript.map((u) => <TranscriptLine key={u.id} u={u} mark={mark === u.id} />)
          )}
        </div>
      </section>

      <EmailCard callId={memo.call_id} />

      <div className="memo__actions">
        <button className="btn btn--secondary" onClick={() => window.print()}>Print</button>
        <button className="btn btn--secondary" onClick={newCall}>Back to start</button>
      </div>
      <p className="muted memo__note">{memo.note}</p>
    </>
  );
}

export function MemoScreen() {
  const callId = useAppStore((s) => s.memoCallId);
  const { load, retry } = useMemoLoad(callId);
  const liveDuration = useCallStore((s) =>
    s.callId === callId && s.startedAtMs !== null && s.endedAtMs !== null ? formatClock(s.endedAtMs - s.startedAtMs) : null,
  );

  return (
    <main className="memo">
      <div className="memo__inner">
        {load.state === "ready" ? (
          <MemoView memo={load.memo} />
        ) : (
          <>
            <p className="memo__eyebrow">Your call memo</p>
            {load.state === "writing" ? (
              <div className="memo__status" role="status">
                <h1 className="memo__title">Writing your memo…</h1>
                {liveDuration && (
                  <p className="muted">
                    Your call lasted <span className="numbers">{liveDuration}</span>.
                  </p>
                )}
              </div>
            ) : (
              <div className="memo__status" role="alert">
                <h1 className="memo__title">Your memo isn&apos;t ready</h1>
                <p>{FAILED_TEXT}</p>
                <div className="memo__actions">
                  <button className="btn" onClick={retry}>Retry</button>
                  <button className="btn btn--secondary" onClick={newCall}>Back to start</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
