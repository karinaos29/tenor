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
  | RiskUpdated
  | TacticFlagged;

/**
 * Every type that crosses the wire. Generated root; import the member types.
 */
export interface TenorWire {
  event: TenorEvent;
  replayList: ReplayList;
  evalResponse: EvalResponse;
  callMemoResponse: CallMemoResponse;
  emailRequest: EmailRequest;
  emailResult: EmailResult;
  emailDefaults: EmailDefaults;
  savedCallList: SavedCallList;
  voiceEnrolled: VoiceEnrolled;
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
  /**
   * The user's voice from the mic check (POST /api/voice)
   */
  voice_id: string | null;
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
  reason: "first_turn" | "loudness" | "tone" | "voice" | "manual";
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
export interface TacticFlagged {
  ts: string;
  type: "tactic.flagged";
  flag: TacticFlag;
}
export interface TacticFlag {
  id: string;
  tactic:
    "urgency" | "scarcity" | "social_proof" | "secrecy" | "guarantee" | "fomo_regret" | "skip_checks" | "authority";
  /**
   * Plain-words name shown to the user, e.g. 'Keeping it secret'
   */
  label: string;
  /**
   * The caller's words that triggered it
   */
  quote: string;
  severity: "mild" | "strong";
  utterance_id: string;
  /**
   * Classifier probability (1.0 for a rule-only match)
   */
  score: number;
  source: "classifier" | "rule" | "both";
}
export interface ReplayList {
  replays: ReplayInfo[];
}
export interface ReplayInfo {
  id: string;
  title: string;
  duration_s: number;
}
export interface EvalResponse {
  report: EvalReport | null;
}
export interface EvalReport {
  run_id: string;
  created_at: string;
  commit: string;
  note: string;
  /**
   * What the benchmark is made of, in plain words
   */
  data: string;
  targets: Target[];
  detectors: DetectorScores[];
  calls: CallResult[];
  latency: StageLatency[];
  audio: boolean;
}
export interface Target {
  label: string;
  target: string;
  measured: string;
  met: boolean | null;
}
export interface DetectorScores {
  name: string;
  rows: MetricRow[];
  micro: MetricRow;
  any_tactic: MetricRow;
  latency_ms_median: number;
  note: string;
}
export interface MetricRow {
  tactic: string;
  label: string;
  precision: number;
  recall: number;
  f1: number;
  support: number;
}
export interface CallResult {
  name: string;
  kind: "manipulative" | "honest";
  hard_honest: boolean;
  /**
   * e.g. 'high or critical' / 'low or medium'
   */
  expected: string;
  risk_score: number;
  risk_level: string;
  ok: boolean;
  false_claims_expected: number;
  false_claims_caught: number;
  tactic_recall: number | null;
  tactic_precision: number | null;
  max_visible_suggestions: number;
  /**
   * Memo written, with no buy/sell/safe/scam wording
   */
  memo_ok: boolean | null;
  /**
   * Hang-up to memo ready, seconds
   */
  memo_s: number | null;
}
export interface StageLatency {
  stage: string;
  n: number;
  median_ms: number;
  p95_ms: number;
}
export interface CallMemoResponse {
  status: "live" | "writing" | "ready" | "failed" | "unknown";
  memo: Memo | null;
}
/**
 * Built from the call's facts; the LLM may only word the summary (under guards).
 */
export interface Memo {
  call_id: string;
  created_at: string;
  started_at: string;
  duration_s: number;
  source: "mic" | "replay";
  replay_id: string | null;
  risk_score: number | null;
  risk_level: ("low" | "medium" | "high" | "critical") | null;
  headline: string;
  summary: string;
  summary_wording: "template" | "gemini";
  sections: MemoSection[];
  transcript: Utterance[];
  /**
   * What the memo is and isn't (Tenor never says buy or sell)
   */
  note: string;
}
export interface MemoSection {
  id: string;
  title: string;
  items: MemoItem[];
  /**
   * Shown when there are no items
   */
  empty: string;
}
export interface MemoItem {
  text: string;
  detail: string;
  /**
   * Moment in the call (seconds), for 'jump to transcript'
   */
  t: number | null;
  source: string;
  tone: "neutral" | "ok" | "warn" | "danger";
}
export interface EmailRequest {
  to: string;
}
export interface EmailResult {
  ok: boolean;
  message: string;
  id?: string | null;
}
export interface EmailDefaults {
  /**
   * A Resend key is set
   */
  configured: boolean;
  /**
   * Prefilled recipient (MEMO_EMAIL_TO), if any
   */
  to: string | null;
}
export interface SavedCallList {
  calls: SavedCall[];
}
export interface SavedCall {
  call_id: string;
  started_at: string;
  source: string;
  replay_id: string | null;
  status: string;
  risk_level: string | null;
  headline: string | null;
}
/**
 * POST /api/voice: the user's voice print from the mic check.
 */
export interface VoiceEnrolled {
  ok: boolean;
  voice_id?: string | null;
  message: string;
}
