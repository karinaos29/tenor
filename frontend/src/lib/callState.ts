import type { CallEnded, Claim, Offer, ResearchItem, RiskUpdated, Suggestion, TenorEvent, Utterance } from "./events.gen";

export type CallPhase = "connecting" | "live" | "ended" | "lost";
export type Role = "caller" | "user";

export interface CallState {
  phase: CallPhase;
  source: "mic" | "replay" | null;
  replayTitle: string | null;
  callId: string | null;
  startedAtMs: number | null;
  endedAtMs: number | null;
  utterances: Utterance[];
  userIndices: number[] | null;
  labelsLocked: boolean;
  transcriber: { state: "connecting" | "live" | "reconnecting" | "unavailable"; detail: string };
  endReason: CallEnded["reason"] | null;
  lostMessage: string | null;
  offer: Offer | null;
  claims: Claim[];
  research: Record<string, ResearchItem>;
  suggestions: { visible: Suggestion[]; earlier: Suggestion[] };
  risk: RiskUpdated | null;
}

export const LOST_MESSAGE = "Lost connection to Tenor's server. This call is no longer being transcribed.";

export const initialCallState: CallState = {
  phase: "connecting",
  source: null,
  replayTitle: null,
  callId: null,
  startedAtMs: null,
  endedAtMs: null,
  utterances: [],
  userIndices: null,
  labelsLocked: false,
  transcriber: { state: "connecting", detail: "" },
  endReason: null,
  lostMessage: null,
  offer: null,
  claims: [],
  research: {},
  suggestions: { visible: [], earlier: [] },
  risk: null,
};

const CALL_EVENT_TYPES = new Set<string>([
  "call.started",
  "transcriber.status",
  "speakers.updated",
  "utterance.partial",
  "utterance.final",
  "call.ended",
  "offer.updated",
  "offer.changed",
  "claim.checked",
  "research.ready",
  "suggestions.updated",
  "risk.updated",
]);

/** Parse a raw socket message. Returns null for anything that isn't a known server call event. */
export function parseCallEvent(raw: string): TenorEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const type = (data as { type?: unknown }).type;
  return typeof type === "string" && CALL_EVENT_TYPES.has(type) ? (data as TenorEvent) : null;
}

/** Role to show for a line. The diarized speaker number wins once we know which ones are the user
 * (diarization can split one voice into two numbers). */
export function displayRole(u: Utterance, userIndices: number[] | null): Role {
  if (userIndices === null) return u.speaker;
  return userIndices.includes(u.speaker_index) ? "user" : "caller";
}

function upsert(list: Utterance[], u: Utterance, isFinal: boolean): Utterance[] {
  const i = list.findIndex((x) => x.id === u.id);
  if (i === -1) return [...list, { ...u, is_final: isFinal }];
  if (list[i].is_final && !isFinal) return list; // late partial
  const next = list.slice();
  next[i] = { ...u, is_final: isFinal };
  return next;
}

/** Pure transition for an incoming server event. */
export function applyCallEvent(state: CallState, event: TenorEvent, nowMs: number): CallState {
  switch (event.type) {
    case "call.started":
      return { ...state, phase: "live", callId: event.call_id, source: event.source, startedAtMs: nowMs };
    case "utterance.partial":
      return { ...state, utterances: upsert(state.utterances, event.utterance, false) };
    case "utterance.final":
      return { ...state, utterances: upsert(state.utterances, event.utterance, true) };
    case "speakers.updated":
      return { ...state, userIndices: event.user_indices, labelsLocked: event.locked };
    case "transcriber.status":
      return { ...state, transcriber: { state: event.state, detail: event.detail } };
    case "offer.updated":
      return { ...state, offer: event.offer };
    case "claim.checked": {
      const i = state.claims.findIndex((c) => c.id === event.claim.id);
      const claims = state.claims.slice();
      if (i === -1) claims.push(event.claim);
      else claims[i] = event.claim;
      return { ...state, claims };
    }
    case "research.ready":
      return { ...state, research: { ...state.research, [event.item.id]: event.item } };
    case "suggestions.updated":
      return { ...state, suggestions: { visible: event.visible, earlier: event.earlier } };
    case "risk.updated":
      return { ...state, risk: event };
    case "call.ended":
      return state.phase === "lost" ? state : { ...state, phase: "ended", endReason: event.reason, endedAtMs: nowMs };
    default:
      return state;
  }
}

export function applyCallLost(state: CallState, nowMs: number): CallState {
  if (state.phase === "ended" || state.phase === "lost") return state;
  return { ...state, phase: "lost", endedAtMs: nowMs, lostMessage: LOST_MESSAGE };
}

export function beginCall(source: "mic" | "replay", replayTitle: string | null): CallState {
  return { ...initialCallState, source, replayTitle };
}

export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
