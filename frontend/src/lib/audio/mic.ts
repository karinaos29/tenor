import workletUrl from "./capture.worklet?worker&url";
import type { CaptureMessage } from "./capture.worklet";
import { dbfsToLevel } from "./pcm";
import { initialMicState, useMicStore } from "../../stores/mic";
import { onVoiceFrame, startVoiceCheck, stopVoiceCheck } from "./voiceCheck";
import type { MicPermission } from "../../stores/mic";

/** Constraints matter: AGC would erase the loudness difference used to tell You from Caller. */
export const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
};

type FrameSink = (frame: Int16Array) => void;

let stream: MediaStream | null = null;
let context: AudioContext | null = null;
let node: AudioWorkletNode | null = null;
let sink: FrameSink | null = null;

export function classifyMicError(err: unknown): MicPermission {
  const name = (err as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") return "no_device";
  return "error";
}

/** Ask for the microphone (once) and start the level meter. Safe to call again while granted. */
export async function checkMicrophone(): Promise<void> {
  if (stream) return;
  const set = (permission: MicPermission) => useMicStore.setState({ permission, level: 0 });
  set("asking");
  let s: MediaStream;
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      set("error");
      return;
    }
    s = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
  } catch (err) {
    set(classifyMicError(err));
    return;
  }
  stream = s;
  try {
    const ctx = new AudioContext();
    context = ctx;
    await ctx.audioWorklet.addModule(workletUrl);
    const source = ctx.createMediaStreamSource(s);
    const worklet = new AudioWorkletNode(ctx, "tenor-capture", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
    worklet.port.onmessage = (e: MessageEvent<CaptureMessage>) => {
      useMicStore.setState({ level: dbfsToLevel(e.data.dbfs) });
      onVoiceFrame(e.data.frame, e.data.dbfs);
      sink?.(e.data.frame);
    };
    // Muted output keeps the node pulled by the audio graph without playing the mic back.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    source.connect(worklet).connect(mute).connect(ctx.destination);
    node = worklet;
    await ctx.resume();
    useMicStore.setState({ permission: "granted", level: 0 });
    startVoiceCheck();
  } catch {
    releaseMicrophone();
    set("error");
  }
}

/** Where captured 16 kHz frames go (the call socket), or null to drop them. */
export function setFrameSink(next: FrameSink | null): void {
  sink = next;
}

/** Stop all tracks and close the audio context. */
export function releaseMicrophone(): void {
  sink = null;
  if (node) node.port.onmessage = null;
  node?.disconnect();
  node = null;
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  void context?.close().catch(() => undefined);
  context = null;
  stopVoiceCheck();
  // A learned voice outlives the microphone: the next call can use it without a new check.
  useMicStore.setState((s) =>
    s.voice === "ready"
      ? { ...initialMicState, voice: "ready", voiceId: s.voiceId, voiceProgress: 1, voiceMessage: s.voiceMessage }
      : { ...initialMicState },
  );
}
