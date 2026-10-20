import type { TenorEvent } from "./events.gen";
import type { HealthState } from "../stores/health";

const SERVER_EVENT_TYPES = new Set<string>(["health.status", "health.pong"]);

/** Parse a raw socket message. Returns null for anything that isn't a known server event. */
export function parseServerEvent(raw: string): TenorEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const type = (data as { type?: unknown }).type;
  return typeof type === "string" && SERVER_EVENT_TYPES.has(type) ? (data as TenorEvent) : null;
}

/** Pure transition for an incoming server event. nowMs = Date.now(), perfNowMs = performance.now(). */
export function applyHealthEvent(
  state: HealthState,
  event: TenorEvent,
  nowMs: number,
  perfNowMs: number = nowMs,
): HealthState {
  switch (event.type) {
    case "health.status":
      return {
        ...state,
        status: "connected",
        services: event.services,
        version: event.version,
        lastCheckedAt: nowMs,
        retryInSec: null,
      };
    case "health.pong":
      return {
        ...state,
        status: "connected",
        rttMs: Math.max(0, Math.round(perfNowMs - event.client_sent_ms)),
        lastCheckedAt: nowMs,
        retryInSec: null,
      };
    default:
      return state;
  }
}

/** Pure transition when the connection failed or timed out. */
export function applyHealthFailure(state: HealthState, retryInSec: number): HealthState {
  return { ...state, status: "offline", rttMs: null, retryInSec };
}

/** Pure transition when a (re)connect attempt starts after being offline. */
export function applyHealthConnecting(state: HealthState): HealthState {
  return { ...state, status: "connecting", retryInSec: null };
}

/** Backoff: 1, 2, 4, 8 s, capped at 10 s. attempt starts at 0. */
export function backoffSeconds(attempt: number): number {
  return Math.min(10, 2 ** attempt);
}
