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
  | OfferChanged
  | ClaimChecked
  | ResearchReady
  | SuggestionsUpdated
  | RiskUpdated;

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
   * Voice number: the diarized speaker from speech-to-text, or 100 + n for a second voice the labeler found inside speaker n by loudness
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
 * Which voices (`Utterance.speaker_index`) are the user. A list, because diarization
 * can split one voice in two. Everyone else is the caller.
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
/**
 * A claim with its verdict. The verdict comes from data and arithmetic, never from the LLM.
 */
export interface ClaimChecked {
  ts: string;
  type: "claim.checked";
  claim: Claim;
}
/**
 * A factual statement by the caller. The LLM may extract it; only data decides its status (M3).
 */
export interface Claim {
  id: string;
  text: string;
  metric: "price_change" | "return" | "guarantee" | "event" | "fee" | "price" | "other";
  claimed_value: number | null;
  unit: string | null;
  period: string | null;
  /**
   * Ticker or company the claim is about
   */
  subject: string | null;
  utterance_id: string;
  status: "checking" | "verified" | "false" | "not_found" | "unverifiable";
  actual_value: number | null;
  source: string | null;
  checked_in_ms: number | null;
  /**
   * Plain-words detail of the check, e.g. 'last 13 weeks'
   */
  note: string | null;
}
/**
 * A research item started (prefetching) or finished (ready / failed).
 */
export interface ResearchReady {
  ts: string;
  type: "research.ready";
  item: ResearchItem;
}
export interface ResearchItem {
  id: string;
  topic: "ticker" | "firm";
  /**
   * Ticker or firm name
   */
  subject: string;
  title: string;
  status: "prefetching" | "ready" | "failed";
  summary: string;
  facts: Fact[];
  source: string;
  checked_at: string | null;
  wording: "template" | "gemini";
  /**
   * For firms: the register result, so rules don't parse text
   */
  finding: ("registered" | "not_registered") | null;
}
export interface Fact {
  label: string;
  value: string;
  source: string;
}
/**
 * At most four visible suggestions, highest priority first; the rest are kept for the memo.
 */
export interface SuggestionsUpdated {
  ts: string;
  type: "suggestions.updated";
  visible: Suggestion[];
  earlier: Suggestion[];
}
export interface Suggestion {
  id: string;
  kind: "say_this" | "research";
  title: string;
  /**
   * For say_this: the words to say, first person
   */
  text: string;
  priority: number;
  status: "prefetching" | "ready";
  /**
   * Why Tenor suggests it, in plain words
   */
  reason: string;
  source: string;
  checked_at: string | null;
  expires_at: string | null;
}
export interface RiskUpdated {
  ts: string;
  type: "risk.updated";
  score: number;
  level: "low" | "medium" | "high" | "critical";
  reasons: RiskReason[];
}
export interface RiskReason {
  label: string;
  points: number;
}
export interface ReplayList {
  replays: ReplayInfo[];
}
export interface ReplayInfo {
  id: string;
  title: string;
  duration_s: number;
}
