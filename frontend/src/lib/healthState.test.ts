import { describe, expect, it } from "vitest";
import { applyHealthConnecting, applyHealthEvent, applyHealthFailure, backoffSeconds, parseServerEvent } from "./healthState";
import { initialHealthState } from "../stores/health";

const services = { transcription: true, llm: false, market_data: true, email: false };

describe("applyHealthEvent", () => {
  it("marks connected on health.status", () => {
    const s = applyHealthEvent(
      initialHealthState,
      { type: "health.status", ts: "t", version: "0.1.0", services },
      1000,
    );
    expect(s.status).toBe("connected");
    expect(s.services).toEqual(services);
    expect(s.version).toBe("0.1.0");
    expect(s.lastCheckedAt).toBe(1000);
  });

  it("computes rtt from pong", () => {
    const s = applyHealthEvent(
      initialHealthState,
      { type: "health.pong", ts: "t", client_sent_ms: 100, server_ms: 1 },
      5000,
      112,
    );
    expect(s.rttMs).toBe(12);
    expect(s.lastCheckedAt).toBe(5000);
  });

});

describe("parseServerEvent", () => {
  it("accepts known server events", () => {
    expect(parseServerEvent(JSON.stringify({ type: "health.pong", ts: "t", client_sent_ms: 1, server_ms: 0 }))?.type).toBe(
      "health.pong",
    );
  });

  it("ignores unknown types, client-only types and invalid JSON", () => {
    expect(parseServerEvent(JSON.stringify({ type: "something.else" }))).toBeNull();
    expect(parseServerEvent(JSON.stringify({ type: "health.ping", ts: "t", client_sent_ms: 1 }))).toBeNull();
    expect(parseServerEvent("not json")).toBeNull();
    expect(parseServerEvent("null")).toBeNull();
  });
});

describe("failure handling", () => {
  it("goes offline with retry countdown and clears rtt", () => {
    const s = applyHealthFailure({ ...initialHealthState, status: "connected", rttMs: 9 }, 2);
    expect(s.status).toBe("offline");
    expect(s.retryInSec).toBe(2);
    expect(s.rttMs).toBeNull();
  });

  it("returns to connecting on retry", () => {
    const s = applyHealthConnecting(applyHealthFailure(initialHealthState, 1));
    expect(s.status).toBe("connecting");
    expect(s.retryInSec).toBeNull();
  });

  it("backs off 1,2,4,8 then caps at 10", () => {
    expect([0, 1, 2, 3, 4, 5].map(backoffSeconds)).toEqual([1, 2, 4, 8, 10, 10]);
  });
});
