import { create } from "zustand";

export type Screen = "start" | "live" | "eval";

interface AppStore {
  screen: Screen;
  /** Inline error shown on the Start screen after a call could not begin. */
  startError: string | null;
  setScreen: (screen: Screen) => void;
  setStartError: (message: string | null) => void;
}

export const useAppStore = create<AppStore>()((set) => ({
  screen: "start",
  startError: null,
  setScreen: (screen) => set({ screen }),
  setStartError: (startError) => set({ startError }),
}));
