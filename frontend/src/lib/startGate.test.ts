import { describe, expect, it } from "vitest";
import { replayReason, startReason } from "./startGate";

const ok = { consent: true, mic: "granted", status: "connected", transcription: true } as const;

describe("startGate", () => {
  it("enables when everything is ready", () => {
    expect(startReason(ok)).toBeNull();
  });
  it("gives reasons in priority order", () => {
    expect(startReason({ ...ok, status: "offline", consent: false })).toBe("Tenor's server isn't reachable yet.");
    expect(startReason({ ...ok, transcription: false, consent: false })).toBe("Transcription isn't set up: its key is missing.");
    expect(startReason({ ...ok, consent: false, mic: "idle" })).toBe("Tick the box above first.");
    expect(startReason({ ...ok, mic: "denied" })).toBe("Check your microphone first.");
  });
  it("replay needs only the server and the key", () => {
    expect(replayReason({ ...ok, consent: false, mic: "idle" })).toBeNull();
    expect(replayReason({ ...ok, transcription: false })).not.toBeNull();
    expect(replayReason({ ...ok, status: "connecting" })).not.toBeNull();
  });
});
