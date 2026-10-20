import { describe, expect, it } from "vitest";
import { applyCallEvent, applyCallLost, beginCall, displayRole, formatClock, parseCallEvent } from "./callState";
import type { Utterance, TenorEvent } from "./events.gen";

const ts = "2026-01-01T00:00:00Z";
const utt = (id: string, text: string, speaker: "caller" | "user" = "caller", idx = 0, fin = false): Utterance => ({
  id, speaker, speaker_index: idx, text, t_start: 0, t_end: 1, is_final: fin,
});
const partial = (u: Utterance): TenorEvent => ({ ts, type: "utterance.partial", utterance: u });
const final = (u: Utterance): TenorEvent => ({ ts, type: "utterance.final", utterance: { ...u, is_final: true } });

describe("callState", () => {
  const s0 = beginCall("mic", null);

  it("replaces a partial with the final of the same id, keeping order", () => {
    let s = applyCallEvent(s0, partial(utt("a", "hel")), 0);
    s = applyCallEvent(s, partial(utt("b", "x", "user", 1)), 0);
    s = applyCallEvent(s, partial(utt("a", "hello")), 0);
    s = applyCallEvent(s, final(utt("a", "hello there")), 0);
    expect(s.utterances.map((u) => u.id)).toEqual(["a", "b"]);
    expect(s.utterances[0]).toMatchObject({ text: "hello there", is_final: true });
    expect(s.utterances[1].is_final).toBe(false);
  });

  it("ignores a late partial for an already-final id", () => {
    let s = applyCallEvent(s0, final(utt("a", "done")), 0);
    s = applyCallEvent(s, partial(utt("a", "do")), 0);
    expect(s.utterances).toHaveLength(1);
    expect(s.utterances[0]).toMatchObject({ text: "done", is_final: true });
  });

  it("relabels all lines on speakers.updated", () => {
    let s = applyCallEvent(s0, final(utt("a", "one", "caller", 0)), 0);
    s = applyCallEvent(s, final(utt("b", "two", "user", 1)), 0);
    const roles = (st: typeof s) => st.utterances.map((u) => displayRole(u, st.userIndices));
    // Before any speakers.updated, the role the server sent is used.
    expect(roles(s)).toEqual(["caller", "user"]);
    s = applyCallEvent(s, { ts, type: "speakers.updated", user_indices: [0], reason: "manual", locked: true }, 0);
    expect(roles(s)).toEqual(["user", "caller"]);
    expect(s.labelsLocked).toBe(true);
    // An empty list means nobody is "You" (e.g. only the caller has spoken).
    s = applyCallEvent(s, { ts, type: "speakers.updated", user_indices: [], reason: "loudness", locked: false }, 0);
    expect(roles(s)).toEqual(["caller", "caller"]);
  });

  it("keeps both halves of a voice that diarization split in two", () => {
    let s = applyCallEvent(s0, final(utt("a", "Hello?", "user", 0)), 0);
    s = applyCallEvent(s, final(utt("b", "Good afternoon.", "caller", 1)), 0);
    s = applyCallEvent(s, final(utt("c", "What is this about?", "user", 2)), 0);
    s = applyCallEvent(s, { ts, type: "speakers.updated", user_indices: [0, 2], reason: "loudness", locked: false }, 0);
    expect(s.utterances.map((u) => displayRole(u, s.userIndices))).toEqual(["user", "caller", "user"]);
  });

  it("tracks transcriber status", () => {
    const s = applyCallEvent(s0, { ts, type: "transcriber.status", state: "unavailable", detail: "no_key" }, 0);
    expect(s.transcriber).toEqual({ state: "unavailable", detail: "no_key" });
  });

  it("moves through phases", () => {
    let s = applyCallEvent(s0, { ts, type: "call.started", call_id: "c1", source: "mic", replay_id: null }, 1000);
    expect(s).toMatchObject({ phase: "live", callId: "c1", startedAtMs: 1000 });
    s = applyCallEvent(s, { ts, type: "call.ended", reason: "user", detail: "" }, 5000);
    expect(s).toMatchObject({ phase: "ended", endReason: "user", endedAtMs: 5000 });
    expect(applyCallLost(s, 6000).phase).toBe("ended");
    expect(applyCallLost(s0, 1).phase).toBe("lost");
  });

  it("parses only known server events", () => {
    expect(parseCallEvent('{"type":"call.ended"}')).not.toBeNull();
    expect(parseCallEvent('{"type":"call.start"}')).toBeNull();
    expect(parseCallEvent("nope")).toBeNull();
  });

  it("formats clock", () => {
    expect(formatClock(65_000)).toBe("1:05");
  });
});
