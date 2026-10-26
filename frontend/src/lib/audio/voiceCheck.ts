import { apiUrl } from "../backend";
import type { VoiceEnrolled } from "../events.gen";
import { useMicStore } from "../../stores/mic";

export const VOICE_SPEECH_S = 4; // speech the voice check needs
export const VOICE_GATE_DBFS = -50; // quieter frames aren't speech
const FRAME_S = 0.08;
const MAX_FRAMES = Math.round(15 / FRAME_S); // keep the last 15 s
const TIMEOUT_MS = 15000;
const FAILED = "Tenor couldn't learn your voice. Calls still work without it.";

let frames: Int16Array[] = [];
let speech = 0;

/** Start (or restart) listening for the voice check, unless Tenor already knows the voice. */
export function startVoiceCheck(): void {
  frames = [];
  speech = 0;
  if (useMicStore.getState().voice === "ready") return;
  useMicStore.setState({ voice: "listening", voiceProgress: 0, voiceMessage: "" });
}

/** Stop listening (a call is starting: from now on both voices are in the room). */
export function stopVoiceCheck(): void {
  frames = [];
  speech = 0;
  if (useMicStore.getState().voice === "listening") useMicStore.setState({ voice: "idle", voiceProgress: 0 });
}

/** Feed one captured 80 ms frame. Sends the recording once enough speech was heard. */
export function onVoiceFrame(frame: Int16Array, dbfs: number): void {
  if (useMicStore.getState().voice !== "listening") return;
  frames.push(frame);
  if (frames.length > MAX_FRAMES) frames.shift();
  if (dbfs > VOICE_GATE_DBFS) speech += FRAME_S;
  useMicStore.setState({ voiceProgress: Math.min(1, speech / VOICE_SPEECH_S) });
  if (speech >= VOICE_SPEECH_S) void submit();
}

async function submit(): Promise<void> {
  const total = frames.reduce((n, f) => n + f.length, 0);
  const body = new Int16Array(total);
  let at = 0;
  for (const f of frames) {
    body.set(f, at);
    at += f.length;
  }
  frames = [];
  speech = 0;
  useMicStore.setState({ voice: "learning" });
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(apiUrl("/api/voice"), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: body.buffer,
      signal: ctrl.signal,
    });
    const result = res.ok ? ((await res.json()) as VoiceEnrolled) : null;
    if (result?.ok && result.voice_id) {
      useMicStore.setState({ voice: "ready", voiceId: result.voice_id, voiceProgress: 1, voiceMessage: result.message });
    } else {
      useMicStore.setState({ voice: "failed", voiceId: null, voiceMessage: result?.message ?? FAILED });
    }
  } catch {
    useMicStore.setState({ voice: "failed", voiceId: null, voiceMessage: FAILED });
  } finally {
    clearTimeout(timer);
  }
}
