import { checkMicrophone } from "../lib/audio/mic";
import { useMicStore } from "../stores/mic";

const ERRORS = {
  denied: "Tenor can't use the microphone. Allow it in your browser's address bar, then try again.",
  no_device: "No microphone found.",
  error: "Tenor couldn't start the microphone. Try again.",
} as const;

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
        </>
      )}
    </div>
  );
}
