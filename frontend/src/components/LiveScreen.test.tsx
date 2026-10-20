import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { LiveScreen } from "./LiveScreen";
import { beginCall } from "../lib/callState";
import type { TenorEvent, Utterance } from "../lib/events.gen";
import { useCallStore } from "../stores/call";

const ts = "2026-01-01T00:00:00Z";
const utt = (id: string, text: string, speaker: "caller" | "user", idx: number): Utterance => ({
  id, speaker, speaker_index: idx, text, t_start: 0, t_end: 1, is_final: true,
});
const send = (e: TenorEvent) => act(() => useCallStore.getState().dispatch(e));

beforeEach(() => useCallStore.setState({ ...beginCall("mic", null) }));

describe("LiveScreen", () => {
  it("shows empty states", () => {
    render(<LiveScreen />);
    expect(screen.getByText("Words appear here as people speak.")).toBeInTheDocument();
    expect(screen.getByText("Terms fill in as the caller states them.")).toBeInTheDocument();
    expect(screen.getByText("Risk · not scored yet")).toBeInTheDocument();
    expect(screen.getByText("Connecting to the speech service…")).toBeInTheDocument();
  });

  it("labels lines and relabels on speakers.updated", () => {
    render(<LiveScreen />);
    send({ ts, type: "utterance.final", utterance: utt("a", "Act today", "caller", 0) });
    send({ ts, type: "utterance.final", utterance: utt("b", "I need time", "user", 1) });
    send({ ts, type: "utterance.partial", utterance: { ...utt("c", "maybe", "caller", 0), is_final: false } });
    expect(screen.getByText("Caller")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("maybe…")).toBeInTheDocument();
    expect(screen.getByText("Speaking…")).toBeInTheDocument(); // partials have no role yet
    send({ ts, type: "speakers.updated", user_indices: [0], reason: "manual", locked: true });
    // Finals swap roles: "Act today" (speaker 0) is now You, "I need time" (speaker 1) is Caller.
    expect(screen.getByText("Act today").closest(".line")).toHaveClass("line--user");
    expect(screen.getByText("I need time").closest(".line")).toHaveClass("line--caller");
    expect(screen.getByText("Labels set by you")).toBeInTheDocument();
  });

  it.each([
    ["reconnecting", "", "Transcription paused. Reconnecting…"],
    ["unavailable", "unreachable", "Transcription is off: couldn't reach the speech service."],
    ["unavailable", "no_key", "The speech-to-text key is missing."],
  ] as const)("shows transcriber %s (%s)", (state, detail, text) => {
    render(<LiveScreen />);
    send({ ts, type: "transcriber.status", state, detail });
    expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
  });

  it("shows the lost message", () => {
    render(<LiveScreen />);
    act(() => useCallStore.getState().markLost());
    expect(screen.getByText(/Lost connection to Tenor's server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New call" })).toBeInTheDocument();
  });

  it("shows live strip, then ended state with New call", () => {
    render(<LiveScreen />);
    expect(screen.getByRole("button", { name: "End call" })).toBeInTheDocument();
    send({ ts, type: "call.started", call_id: "c", source: "mic", replay_id: null });
    expect(screen.getByText("Listening")).toBeInTheDocument();
    send({ ts, type: "call.ended", reason: "user", detail: "" });
    expect(screen.getByText(/Call ended/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New call" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End call" })).toBeNull();
  });
});
