/* Generated from backend/pipeline/events.py by npm run gen:types. Do not edit. */

export type TenorEvent = HealthStatus | HealthPing | HealthPong;

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
