import { create } from "zustand";

export type MicPermission = "idle" | "asking" | "granted" | "denied" | "no_device" | "error";

export interface MicState {
  permission: MicPermission;
  /** 0..1 meter fill, from dBFS -60..0 */
  level: number;
}

export const initialMicState: MicState = { permission: "idle", level: 0 };

export const useMicStore = create<MicState>()(() => ({ ...initialMicState }));
