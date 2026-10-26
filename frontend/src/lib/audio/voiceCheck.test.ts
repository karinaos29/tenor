import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initialMicState, useMicStore } from "../../stores/mic";
import { VOICE_SPEECH_S, onVoiceFrame, startVoiceCheck, stopVoiceCheck } from "./voiceCheck";

const frame = () => new Int16Array(1280).fill(3000);
const speechFrames = Math.ceil(VOICE_SPEECH_S / 0.08);

function reply(body: unknown, ok = true) {
  return vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(body) });
}

beforeEach(() => {
  useMicStore.setState({ ...initialMicState });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("voice check", () => {
  it("listens, counts only speech, and sends the recording once it has enough", async () => {
    const fetchMock = reply({ ok: true, voice_id: "v1", message: "Tenor knows your voice." });
    vi.stubGlobal("fetch", fetchMock);
    startVoiceCheck();
    expect(useMicStore.getState().voice).toBe("listening");

    onVoiceFrame(frame(), -70); // silence: no progress
    expect(useMicStore.getState().voiceProgress).toBe(0);
    for (let i = 0; i < speechFrames; i++) onVoiceFrame(frame(), -25);
    await vi.waitFor(() => expect(useMicStore.getState().voice).toBe("ready"));

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/voice");
    expect(init.method).toBe("POST");
    expect((init.body as ArrayBuffer).byteLength).toBe((speechFrames + 1) * 1280 * 2);
    expect(useMicStore.getState().voiceId).toBe("v1");
  });

  it("shows the server's message when the voice can't be learned", async () => {
    vi.stubGlobal("fetch", reply({ ok: false, voice_id: null, message: "Tenor couldn't hear enough." }));
    startVoiceCheck();
    for (let i = 0; i < speechFrames; i++) onVoiceFrame(frame(), -25);
    await vi.waitFor(() => expect(useMicStore.getState().voice).toBe("failed"));
    expect(useMicStore.getState().voiceMessage).toBe("Tenor couldn't hear enough.");
  });

  it("falls back to a plain message when the server can't be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    startVoiceCheck();
    for (let i = 0; i < speechFrames; i++) onVoiceFrame(frame(), -25);
    await vi.waitFor(() => expect(useMicStore.getState().voice).toBe("failed"));
    expect(useMicStore.getState().voiceMessage).toMatch(/Calls still work without it/);
  });

  it("stops listening when a call starts, and keeps a voice it already knows", () => {
    startVoiceCheck();
    stopVoiceCheck();
    expect(useMicStore.getState().voice).toBe("idle");

    useMicStore.setState({ voice: "ready", voiceId: "v1" });
    startVoiceCheck();
    expect(useMicStore.getState().voice).toBe("ready");
  });
});
