import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { StartScreen } from "./StartScreen";
import { initialHealthState, setHealthState } from "../stores/health";
import { initialMicState, useMicStore } from "../stores/mic";

const connected = {
  ...initialHealthState,
  status: "connected" as const,
  services: { transcription: true, llm: true, market_data: false, email: true },
};

function mockReplays(replays: unknown[] | "fail") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (replays === "fail") throw new Error("down");
      return { ok: true, json: async () => ({ replays }) };
    }),
  );
}

beforeEach(() => {
  setHealthState({ ...initialHealthState });
  useMicStore.setState({ ...initialMicState });
  mockReplays([{ id: "r1", title: "Test", duration_s: 30 }]);
});
afterEach(() => vi.unstubAllGlobals());

const start = () => screen.getByRole("button", { name: "Start listening" });
const replay = () => screen.getByRole("button", { name: "Replay a test call" });

describe("StartScreen", () => {
  it("explains each disabled reason in order", async () => {
    render(<StartScreen />);
    expect(start()).toBeDisabled();
    expect(screen.getByText("Tenor's server isn't reachable yet.")).toBeInTheDocument();

    await act(async () => setHealthState({ ...connected, services: { ...connected.services, transcription: false } }));
    expect(screen.getByText("Transcription isn't set up: its key is missing.")).toBeInTheDocument();
    expect(replay()).toBeDisabled();

    await act(async () => setHealthState(connected));
    expect(screen.getByText("Tick the box above first.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText("Check your microphone first.")).toBeInTheDocument();

    await act(async () => useMicStore.setState({ permission: "granted", level: 0.4 }));
    expect(start()).toBeEnabled();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "40");
  });

  it("enables replay without consent or microphone", async () => {
    setHealthState(connected);
    render(<StartScreen />);
    await act(async () => {});
    expect(start()).toBeDisabled();
    expect(replay()).toBeEnabled();
  });

  it("disables replay when no test calls exist", async () => {
    mockReplays("fail");
    setHealthState(connected);
    render(<StartScreen />);
    await act(async () => {});
    expect(replay()).toBeDisabled();
    expect(screen.getByText("No test calls found.")).toBeInTheDocument();
  });

  it("shows microphone errors and service labels", async () => {
    useMicStore.setState({ permission: "denied", level: 0 });
    setHealthState(connected);
    render(<StartScreen />);
    expect(screen.getByText(/Tenor can't use the microphone/)).toBeInTheDocument();
    expect(screen.getByText("Key missing")).toBeInTheDocument();
    expect(screen.getAllByText("Ready")).toHaveLength(3);
  });

  it("shows server offline countdown", () => {
    setHealthState({ ...initialHealthState, status: "offline", retryInSec: 4 });
    render(<StartScreen />);
    expect(screen.getByText("Can't reach Tenor's server. Trying again in 4 s.")).toBeInTheDocument();
  });
});
