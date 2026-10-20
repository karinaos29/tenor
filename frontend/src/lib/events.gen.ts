/* Generated from backend/pipeline/events.py by npm run gen:types. Do not edit. */

export type TenorEvent =
  | HealthStatus
  | HealthPing
  | HealthPong
  | CallStart
  | CallStop
  | SpeakersSwap
  | CallStarted
  | UtterancePartial
  | UtteranceFinal
  | SpeakersUpdated
  | TranscriberStatus
  | CallEnded
  | OfferUpdated
  | OfferChanged;

/**
 * Every type that crosses the wire. Generated root; import the member types.
 */
export interface TenorWire {
  event: TenorEvent;
  replayList: ReplayList;
}
/**
 * Server -> client, sent once when the health socket opens.
 */
export interface HealthStatus {
  ts: string;
  type: "health.status";
  version: string;
  services: ServiceStatus;
}
/**
 * Whether each external service has a key configured. Never carries the key.
 */
export interface ServiceStatus {
  transcription: boolean;
  llm: boolean;
  market_data: boolean;
  email: boolean;
}
/**
 * Client -> server. `client_sent_ms` is the client's clock, echoed back.
 */
export interface HealthPing {
  ts: string;
  type: "health.ping";
  client_sent_ms: number;
}
/**
 * Server -> client reply to a ping; the client computes round-trip time.
 */
export interface HealthPong {
  ts: string;
  type: "health.pong";
  client_sent_ms: number;
  /**
   * Server time spent handling the ping, in ms
   */
  server_ms: number;
}
/**
 * Client -> server, first message on /ws/call.
 */
export interface CallStart {
  ts: string;
  type: "call.start";
  source: "mic" | "replay";
  replay_id: string | null;
}
/**
 * Client -> server: the user hung up / pressed End call.
 */
export interface CallStop {
  ts: string;
  type: "call.stop";
}
/**
 * Client -> server: the user says the You/Caller labels are the wrong way round.
 */
export interface SpeakersSwap {
  ts: string;
  type: "speakers.swap";
}
export interface CallStarted {
  ts: string;
  type: "call.started";
  call_id: string;
  source: "mic" | "replay";
  replay_id: string | null;
}
/**
 * Words so far in the current turn; replaced by later partials and finally by utterance.final.
 */
export interface UtterancePartial {
  ts: string;
  type: "utterance.partial";
  utterance: Utterance;
}
/**
 * One speaker turn. Times are seconds from the start of the call.
 */
export interface Utterance {
  id: string;
  /**
   * Role when the utterance was emitted; the UI relabels from speakers.updated
   */
  speaker: "caller" | "user";
  /**
   * Diarized speaker number from speech-to-text
   */
  speaker_index: number;
  text: string;
  t_start: number;
  t_end: number;
  is_final: boolean;
}
export interface UtteranceFinal {
  ts: string;
  type: "utterance.final";
  utterance: Utterance;
}
/**
 * Which diarized speakers are the user (diarization can split one voice in two).
 * Everyone else is the caller.
 */
export interface SpeakersUpdated {
  ts: string;
  type: "speakers.updated";
  user_indices: number[];
  reason: "first_turn" | "loudness" | "manual";
  /**
   * True after a manual swap: automatic relabeling stops
   */
  locked: boolean;
}
export interface TranscriberStatus {
  ts: string;
  type: "transcriber.status";
  state: "connecting" | "live" | "reconnecting" | "unavailable";
  detail: string;
}
export interface CallEnded {
  ts: string;
  type: "call.ended";
  reason: "user" | "replay_finished" | "error";
  detail: string;
}
export interface OfferUpdated {
  ts: string;
  type: "offer.updated";
  offer: Offer;
}
export interface Offer {
  caller_name: Term | null;
  firm: Term | null;
  instrument: Term | null;
  price: Term | null;
  quantity: Term | null;
  total: Term | null;
  fees: Term | null;
  deadline: Term | null;
  payment: Term | null;
  history: TermChange[];
}
/**
 * One term of the offer and where it came from.
 */
export interface Term {
  display: string;
  number: number | null;
  /**
   * Words from the transcript (empty for computed terms)
   */
  said: string;
  utterance_id: string | null;
  t: number | null;
  confidence: "heard" | "matched" | "unsure";
  source: "call" | "computed";
}
export interface TermChange {
  field: "caller_name" | "firm" | "instrument" | "price" | "quantity" | "total" | "fees" | "deadline" | "payment";
  old: Term;
  new: Term;
}
/**
 * A term the caller already stated changed (e.g. 5,000 -> 10,000 shares).
 */
export interface OfferChanged {
  ts: string;
  type: "offer.changed";
  change: TermChange;
}
export interface ReplayList {
  replays: ReplayInfo[];
}
export interface ReplayInfo {
  id: string;
  title: string;
  duration_s: number;
}
