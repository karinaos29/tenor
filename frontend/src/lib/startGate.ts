import type { ConnectionStatus } from "../stores/health";
import type { MicPermission } from "../stores/mic";

export interface GateInput {
  consent: boolean;
  mic: MicPermission;
  status: ConnectionStatus;
  transcription: boolean;
}

const SERVER = "Tenor's server isn't reachable yet.";
const KEY = "Transcription isn't set up: its key is missing.";

function serverReason(g: GateInput): string | null {
  if (g.status !== "connected") return SERVER;
  if (!g.transcription) return KEY;
  return null;
}

/** Why "Start listening" is disabled, in priority order. null = enabled. */
export function startReason(g: GateInput): string | null {
  return serverReason(g) ?? (!g.consent ? "Tick the box above first." : g.mic !== "granted" ? "Check your microphone first." : null);
}

/** Why "Replay a test call" is disabled. Needs only the server and the transcription key. */
export function replayReason(g: GateInput): string | null {
  return serverReason(g);
}
