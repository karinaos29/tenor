import { checkMicrophone } from "../lib/audio/mic";
import { startVoiceCheck } from "../lib/audio/voiceCheck";
import { useMicStore } from "../stores/mic";

const ERRORS = {
  denied: "Tenor can't use the microphone. Allow it in your browser's address bar, then try again.",
  no_device: "No microphone found.",
  error: "Tenor couldn't start the microphone. Try again.",
} as const;

/** Tenor learns the user's voice from one sentence, to tell them apart from the caller. */
function VoiceCheck() {
  const { voice, voiceProgress, voiceMessage } = useMicStore();
  const pct = Math.round(voiceProgress * 100);
  return (
    <div className="voicecheck" aria-live="polite">
      {voice === "listening" && (
        <>
          <p className="mic__hint">
            Now say a sentence, like “This is me, checking my microphone.” Tenor learns your voice, so it can tell you
            apart from the caller.
          </p>
          <div
            className="meter meter--voice"
            role="progressbar"
            aria-label="Voice check"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <div className="meter__fill" style={{ width: `${pct}%` }} />
          </div>
        </>
      )}
      {voice === "learning" && <p className="muted mic__hint">Learning your voice…</p>}
      {voice === "ready" && <p className="ok mic__ok">Tenor knows your voice</p>}
      {voice === "failed" && (
        <>
          <p className="warn mic__msg">{voiceMessage}</p>
          <button className="btn btn--secondary btn--small" onClick={startVoiceCheck}>
            Try the voice check again
          </button>
        </>
      )}
    </div>
  );
}

export function MicCheck() {
  const { permission, level } = useMicStore();
  const pct = Math.round(level * 100);
  return (
    <div className="mic">
      {permission !== "granted" && (
        <button className="btn btn--secondary btn--small" onClick={() => void checkMicrophone()} disabled={permission === "asking"}>
          {permission === "asking" ? "Waiting for permission…" : "Check microphone"}
        </button>
      )}
      {(permission === "denied" || permission === "no_device" || permission === "error") && (
        <p className="warn mic__msg" role="alert">{ERRORS[permission]}</p>
      )}
      {permission === "granted" && (
        <>
          <p className="ok mic__ok">Microphone ready</p>
          <div
            className="meter"
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <div className="meter__fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="muted mic__hint">Say something. The bar should move.</p>
          <VoiceCheck />
        </>
      )}
    </div>
  );
}
