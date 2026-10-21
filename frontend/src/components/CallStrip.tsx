import { useEffect, useState } from "react";
import { endCall, newCall } from "../lib/callSession";
import { formatClock } from "../lib/callState";
import { useAppStore } from "../stores/app";
import { useCallStore } from "../stores/call";
import { RiskPill } from "./RiskPill";

export function CallStrip() {
  const { phase, source, replayTitle, startedAtMs, endedAtMs, offer, callId } = useCallStore();
  const who = [offer?.caller_name?.display, offer?.firm?.display].filter(Boolean).join(" · ");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (phase !== "live") return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [phase]);

  const sourceText = source === "replay" ? `Replay · ${replayTitle ?? "test call"}` : "Microphone";
  const elapsed = startedAtMs === null ? 0 : (phase === "live" ? now : (endedAtMs ?? now)) - startedAtMs;
  const done = phase === "ended" || phase === "lost";

  return (
    <header className="strip">
      <div className="strip__caller">
        <p className="strip__name">{who || "Unknown caller"}</p>
        {!who && <p className="muted strip__sub">Name and firm fill in as the caller says them</p>}
      </div>

      <div className="strip__status">
        {phase === "live" && (
          <>
            <span className="live-dot" aria-hidden="true" />
            <span>Listening</span>
            <span className="numbers">{formatClock(elapsed)}</span>
          </>
        )}
        {phase === "connecting" && <span className="muted">Connecting…</span>}
        {done && (
          <span>
            {phase === "ended" ? "Call ended" : "Call lost"} · <span className="numbers">{formatClock(elapsed)}</span>
          </span>
        )}
        <span className="muted">{sourceText}</span>
      </div>

      <div className="strip__actions">
        <RiskPill />
        {phase === "ended" && callId ? (
          <>
            <button className="btn" onClick={() => useAppStore.getState().openMemo(callId)}>Read your memo</button>
            <button className="btn btn--secondary" onClick={newCall}>New call</button>
          </>
        ) : done ? (
          <button className="btn" onClick={newCall}>New call</button>
        ) : (
          <button className="btn btn--secondary" onClick={endCall}>End call</button>
        )}
      </div>
    </header>
  );
}
