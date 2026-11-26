import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LiveScreen } from "./LiveScreen";
import { beginCall } from "../lib/callState";
import type { Suggestion, TenorEvent } from "../lib/events.gen";
import { useCallStore } from "../stores/call";

const ts = "2026-01-01T00:00:00Z";
const send = (e: TenorEvent) => act(() => useCallStore.getState().dispatch(e));
const request = (over: Partial<Extract<TenorEvent, { type: "secret.requested" }>> = {}): TenorEvent => ({
  ts, type: "secret.requested", kind: "one_time_code", level: "stop", label: "one-time code",
  quote: "Can you read me the code?", utterance_id: "u1", t: 5, ...over,
});
const say = (id: string, text: string): Suggestion => ({
  id, kind: "say_this", title: "t", text, priority: 110, status: "ready", reason: "", source: "", checked_at: ts, expires_at: null,
});

beforeEach(() => useCallStore.setState({ ...beginCall("mic", null) }));

describe("SafetyBanner", () => {
  it("is absent on an ordinary call", () => {
    render(<LiveScreen />);
    expect(screen.queryByText("Don't read it out.")).not.toBeInTheDocument();
  });

  it("warns on a request, then interrupts when an answer starts", () => {
    render(<LiveScreen />);
    send(request());
    expect(screen.getByText("Don't read it out.")).toBeInTheDocument();
    expect(screen.getByText("The caller asked for your one-time code. No real bank or firm needs it on a call.")).toBeInTheDocument();
    expect(screen.getByText("“I don't give that out on the phone. Goodbye.”")).toBeInTheDocument();
    send({ ts, type: "secret.sharing", kind: "one_time_code", label: "one-time code", utterance_id: "u2", t: 9 });
    expect(screen.getByText("Stop. Don't say any more.")).toBeInTheDocument();
    expect(screen.getByText("Already said it? Call your bank on the number on your card.")).toBeInTheDocument();
  });

  it("can be hidden, and comes back when an answer starts", async () => {
    render(<LiveScreen />);
    send(request());
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(screen.queryByText("Don't read it out.")).not.toBeInTheDocument());
    send({ ts, type: "secret.sharing", kind: "one_time_code", label: "one-time code", utterance_id: "u2", t: 9 });
    expect(screen.getByText("Stop. Don't say any more.")).toBeInTheDocument();
  });

  it("uses the milder warning for identity details, and never downgrades a stop", () => {
    render(<LiveScreen />);
    send(request({ kind: "identity", level: "check", label: "personal details" }));
    expect(screen.getByText("Check who's calling first.")).toBeInTheDocument();
    expect(screen.getByText("Check first")).toBeInTheDocument();
    send(request({ kind: "pin", label: "PIN" }));
    send(request({ kind: "identity", level: "check", label: "personal details" }));
    expect(screen.getByText("Don't read it out.")).toBeInTheDocument();
  });

  it("doesn't repeat its line in the suggestions while shown", async () => {
    render(<LiveScreen />);
    send({ ts, type: "suggestions.updated", visible: [say("say-secret", "I don't give that out on the phone. Goodbye."), say("say-x", "Other line")], earlier: [] });
    send(request());
    await waitFor(() => expect(screen.getAllByText("“I don't give that out on the phone. Goodbye.”")).toHaveLength(1));
    expect(screen.getByText("“Other line”")).toBeInTheDocument();
  });
});
