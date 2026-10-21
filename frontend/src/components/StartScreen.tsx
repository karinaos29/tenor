import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { MicCheck } from "./MicCheck";
import { ServiceList } from "./ServiceList";
import { startCall } from "../lib/callSession";
import { replayReason, startReason } from "../lib/startGate";
import type { ReplayInfo, ReplayList, SavedCall, SavedCallList } from "../lib/events.gen";
import { useAppStore } from "../stores/app";
import { useHealthStore } from "../stores/health";
import { useMicStore } from "../stores/mic";
import "./StartScreen.css";

async function fetchReplays(): Promise<ReplayInfo[]> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 4000);
  try {
    const res = await fetch("/api/replays", { signal: ctrl.signal });
    if (!res.ok) return [];
    const body = (await res.json()) as ReplayList;
    return Array.isArray(body.replays) ? body.replays : [];
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

async function fetchLastReadyCall(): Promise<SavedCall | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 4000);
  try {
    const res = await fetch("/api/calls", { signal: ctrl.signal });
    if (!res.ok) return null;
    const body = (await res.json()) as SavedCallList;
    const ready = (Array.isArray(body.calls) ? body.calls : []).filter((c) => c.status === "ready");
    ready.sort((a, b) => b.started_at.localeCompare(a.started_at));
    return ready[0] ?? null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export function StartScreen() {
  const [lastCall, setLastCall] = useState<SavedCall | null>(null);
  const [consent, setConsent] = useState(false);
  const [replays, setReplays] = useState<ReplayInfo[] | null>(null);
  const [picking, setPicking] = useState(false);
  const mic = useMicStore((s) => s.permission);
  const status = useHealthStore((s) => s.status);
  const transcription = useHealthStore((s) => s.services?.transcription === true);
  const startError = useAppStore((s) => s.startError);

  useEffect(() => {
    if (status !== "connected") return;
    let cancelled = false;
    void fetchReplays().then((r) => !cancelled && setReplays(r));
    void fetchLastReadyCall().then((c) => !cancelled && setLastCall(c));
    return () => {
      cancelled = true;
    };
  }, [status]);

  const gate = { consent, mic, status, transcription };
  const startWhy = startReason(gate);
  const serverWhy = replayReason(gate);
  const noReplays = replays !== null && replays.length === 0;
  const replayDisabled = serverWhy !== null || noReplays;

  const onReplay = () => {
    if (!replays || replays.length === 0) return;
    if (replays.length === 1) startCall("replay", replays[0]);
    else setPicking((p) => !p);
  };

  return (
    <main className="start">
      <div className="start__inner">
        <motion.section className="hero" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.25 }}>
          <p className="hero__eyebrow">Tenor · Call copilot</p>
          <h1 className="hero__title">
            Stay calm on <span className="hero__gradient">investment calls</span>
          </h1>
          <p className="hero__sub">
            Put the call on speaker. Tenor listens, writes down both sides, and checks what the caller says.
          </p>
          <div className="hero__buttons">
            <button className="btn" disabled={startWhy !== null} onClick={() => startCall("mic")}>
              Start listening
            </button>
            <button className="btn btn--secondary" disabled={replayDisabled} onClick={onReplay} aria-expanded={picking}>
              Replay a test call
            </button>
          </div>
          {startWhy && <p className="muted hero__reason">{startWhy}</p>}
          {!serverWhy && noReplays && <p className="muted hero__reason">No test calls found.</p>}
          {startError && <p className="warn hero__reason" role="alert">{startError}</p>}
          {picking && replays && replays.length > 1 && (
            <ul className="replays" aria-label="Test calls">
              {replays.map((r) => (
                <li key={r.id}>
                  <button className="replays__item" onClick={() => startCall("replay", r)}>
                    <span>{r.title}</span>
                    <span className="muted numbers">{Math.round(r.duration_s)} s</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </motion.section>

        <motion.section
          className="card before"
          aria-labelledby="before-title"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.25, delay: 0.05 }}
        >
          <h2 id="before-title" className="card__title">Before you start</h2>
          <label className="before__consent">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>I&apos;ll put the call on speaker, and I&apos;m allowed to record calls where I live.</span>
          </label>
          <MicCheck />
          <ServiceList />
        </motion.section>
        <p className="start__reviewers">
          {lastCall && (
            <button className="linkbtn" onClick={() => useAppStore.getState().openMemo(lastCall.call_id)}>
              Read your last memo
            </button>
          )}
          <button className="linkbtn" onClick={() => useAppStore.getState().setScreen("eval")}>
            For reviewers: how Tenor is measured
          </button>
        </p>
      </div>
    </main>
  );
}
