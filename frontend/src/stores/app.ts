import { create } from "zustand";

export type Screen = "start" | "live" | "eval" | "memo";

interface AppStore {
  screen: Screen;
  /** Inline error shown on the Start screen after a call could not begin. */
  startError: string | null;
  /** The call whose memo the memo screen shows. */
  memoCallId: string | null;
  setScreen: (screen: Screen) => void;
  setStartError: (message: string | null) => void;
  openMemo: (callId: string) => void;
}

export const useAppStore = create<AppStore>()((set) => ({
  screen: "start",
  startError: null,
  memoCallId: null,
  setScreen: (screen) => set({ screen }),
  setStartError: (startError) => set({ startError }),
  openMemo: (memoCallId) => set({ memoCallId, screen: "memo" }),
}));
