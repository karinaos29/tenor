import { create } from "zustand";
import { applyCallEvent, applyCallLost, beginCall, initialCallState } from "../lib/callState";
import type { CallState } from "../lib/callState";
import type { TenorEvent } from "../lib/events.gen";

interface CallStore extends CallState {
  begin: (source: "mic" | "replay", replayTitle: string | null) => void;
  dispatch: (event: TenorEvent) => void;
  markLost: () => void;
  reset: () => void;
}

export const useCallStore = create<CallStore>()((set) => ({
  ...initialCallState,
  begin: (source, replayTitle) => set(() => beginCall(source, replayTitle)),
  dispatch: (event) => set((s) => applyCallEvent(s, event, Date.now())),
  markLost: () => set((s) => applyCallLost(s, Date.now())),
  reset: () => set(() => ({ ...initialCallState })),
}));
