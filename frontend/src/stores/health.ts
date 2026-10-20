import { create } from "zustand";
import type { ServiceStatus } from "../lib/events.gen";

export type ConnectionStatus = "connecting" | "connected" | "offline";

export interface HealthState {
  status: ConnectionStatus;
  rttMs: number | null;
  services: ServiceStatus | null;
  version: string | null;
  lastCheckedAt: number | null;
  retryInSec: number | null;
}

export const initialHealthState: HealthState = {
  status: "connecting",
  rttMs: null,
  services: null,
  version: null,
  lastCheckedAt: null,
  retryInSec: null,
};

export const useHealthStore = create<HealthState>()(() => ({ ...initialHealthState }));

export function setHealthState(next: HealthState): void {
  useHealthStore.setState(next);
}
