import { create } from "zustand";

export type MicPermission = "idle" | "asking" | "granted" | "denied" | "no_device" | "error";

/** The voice check: Tenor learns the user's voice from a sentence said at the mic check. */
export type VoiceCheck = "idle" | "listening" | "learning" | "ready" | "failed";

export interface MicState {
  permission: MicPermission;
  /** 0..1 meter fill, from dBFS -60..0 */
  level: number;
  voice: VoiceCheck;
  /** 0..1: how much of the needed speech the voice check has heard */
  voiceProgress: number;
  /** Sent with a live call so "You" is recognized by voice */
  voiceId: string | null;
  voiceMessage: string;
}

export const initialMicState: MicState = {
  permission: "idle",
  level: 0,
  voice: "idle",
  voiceProgress: 0,
  voiceId: null,
  voiceMessage: "",
};

export const useMicStore = create<MicState>()(() => ({ ...initialMicState }));
