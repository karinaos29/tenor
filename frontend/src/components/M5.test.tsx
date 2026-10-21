import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoScreen } from "./MemoScreen";
import { StartScreen } from "./StartScreen";
import { CallStrip } from "./CallStrip";
import { RiskPill } from "./RiskPill";
import { useAppStore } from "../stores/app";
import { initialCallState } from "../lib/callState";
import { useCallStore } from "../stores/call";
import { initialHealthState, setHealthState } from "../stores/health";
import type { Memo } from "../lib/events.gen";

const memo: Memo = {
  call_id: "c1",
  created_at: "2026-10-21T10:00:00Z",
  started_at: "2026-10-21T09:58:00Z",
  duration_s: 125,
  source: "replay",
  replay_id: "r1",
  risk_score: 60,
  risk_level: "high",
  headline: "This call showed several warning signs",
  summary: "The caller promised a fixed return.",
  summary_wording: "gemini",
  sections: [
    { id: "claims", title: "What didn't match", items: [{ text: "Doesn't match data", detail: "Said 12%, data says 4%", t: 65, source: "Fixture, 10:00", tone: "danger" }], empty: "" },
    { id: "tactics", title: "Pressure you heard", items: [], empty: "No pressure tactics were flagged." },
  ],
  transcript: [
    { id: "u1", speaker: "caller", speaker_index: 0, text: "Hello there", t_start: 0, t_end: 3, is_final: true },
    { id: "u2", speaker: "user", speaker_index: 1, text: "Who is this", t_start: 4, t_end: 6, is_final: true },
    { id: "u3", speaker: "caller", speaker_index: 0, text: "Guaranteed twelve percent", t_start: 60, t_end: 64, is_final: true },
    { id: "u4", speaker: "caller", speaker_index: 0, text: "Act today", t_start: 70, t_end: 72, is_final: true },
  ],
  note: "This memo shows facts. It isn't advice.",
};

type Handler = (url: string, init?: RequestInit) => unknown;
function mockApi(handler: Handler) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const r = handler(url, init);
    if (r === "throw") throw new Error("down");
    return { ok: true, json: async () => r };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  useAppStore.setState({ screen: "memo", memoCallId: "c1" });
  useCallStore.setState({ ...initialCallState });
  setHealthState({ ...initialHealthState });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const flush = () => act(async () => {});
const email = (configured = true, to: string | null = "e@example.com") => ({ configured, to });

describe("MemoScreen", () => {
  it("polls from writing to ready", async () => {
    vi.useFakeTimers();
    let n = 0;
    mockApi((url) => (url.includes("/memo") ? (++n < 3 ? { status: "writing", memo: null } : { status: "ready", memo }) : email()));
    render(<MemoScreen />);
    await flush();
    expect(screen.getByText("Writing your memo…")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(screen.getByRole("heading", { level: 1, name: memo.headline })).toBeInTheDocument();
    expect(screen.getByText("Summary worded by Gemini from the facts below")).toBeInTheDocument();
  });

  it("shows failure and retries", async () => {
    let fail = true;
    mockApi((url) => (url.includes("/memo") ? (fail ? { status: "failed", memo: null } : { status: "ready", memo }) : email()));
    render(<MemoScreen />);
    await flush();
    expect(screen.getByText(/Couldn't write the memo/)).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(screen.getByText(memo.headline)).toBeInTheDocument();
  });

  it("renders sections, empty text and hides the transcript by default", async () => {
    mockApi((url) => (url.includes("/memo") ? { status: "ready", memo } : email()));
    render(<MemoScreen />);
    await flush();
    expect(screen.getByRole("heading", { level: 2, name: "What didn't match" })).toBeInTheDocument();
    expect(screen.getByText("Doesn't match data")).toBeInTheDocument();
    expect(screen.getByText("No pressure tactics were flagged.")).toBeInTheDocument();
    expect(screen.getByText(memo.note)).toBeInTheDocument();
    expect(screen.getByText("Hello there")).not.toBeVisible();
  });

  it("opens the transcript and marks the closest earlier line", async () => {
    mockApi((url) => (url.includes("/memo") ? { status: "ready", memo } : email()));
    render(<MemoScreen />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "at 1:05" }));
    await flush();
    expect(screen.getByText("Guaranteed twelve percent")).toBeVisible();
    expect(document.getElementById("memo-line-u3")).toHaveAttribute("data-marked", "true");
    expect(document.getElementById("memo-line-u4")).not.toHaveAttribute("data-marked");
  });

  it("prefills email and reports success and failure", async () => {
    let result: unknown = { ok: true, message: "Sent to e@example.com.", id: "x" };
    const fn = mockApi((url, init) => {
      if (url.includes("/memo")) return { status: "ready", memo };
      if (init?.method === "POST") return result;
      return email();
    });
    render(<MemoScreen />);
    await flush();
    expect(screen.getByLabelText("Email address")).toHaveValue("e@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await flush();
    expect(screen.getByText("Sent to e@example.com.")).toBeInTheDocument();
    const post = fn.mock.calls.find((c) => c[1]?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ to: "e@example.com" });
    result = { ok: false, message: "Couldn't send: bad address." };
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await flush();
    expect(screen.getByText("Couldn't send: bad address.")).toBeInTheDocument();
  });

  it("disables Send when email is not configured", async () => {
    mockApi((url) => (url.includes("/memo") ? { status: "ready", memo } : email(false, null)));
    render(<MemoScreen />);
    await flush();
    expect(screen.getByText(/Email isn't set up yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});

describe("memo entry points", () => {
  it("Start screen links to the last ready memo", async () => {
    setHealthState({ ...initialHealthState, status: "connected", services: { transcription: true, llm: true, market_data: false, email: true } });
    mockApi((url) =>
      url.includes("/api/calls")
        ? { calls: [{ call_id: "old", started_at: "2026-10-20T09:00:00Z", source: "mic", replay_id: null, status: "ready", risk_level: null, headline: null }] }
        : { replays: [] },
    );
    render(<StartScreen />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Read your last memo" }));
    expect(useAppStore.getState().screen).toBe("memo");
    expect(useAppStore.getState().memoCallId).toBe("old");
  });

  it("call strip offers the memo after the call ends", () => {
    useAppStore.setState({ screen: "live", memoCallId: null });
    useCallStore.setState({ ...initialCallState, phase: "ended", callId: "c9", source: "mic" });
    render(<CallStrip />);
    expect(screen.getByRole("button", { name: "New call" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Read your memo" }));
    expect(useAppStore.getState().memoCallId).toBe("c9");
  });
});

describe("RiskPill popover", () => {
  beforeEach(() => {
    useCallStore.setState({
      ...initialCallState,
      risk: { ts: "t", type: "risk.updated", score: 30, level: "medium", reasons: [{ points: 30, label: "A claim doesn't match data" }] } as never,
    });
  });

  it("opens and closes by click and Escape", () => {
    render(<RiskPill />);
    const pill = screen.getByRole("button", { name: /Risk/ });
    expect(pill).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(pill);
    expect(pill).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("A claim doesn't match data")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(pill).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(pill);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("A claim doesn't match data")).toBeNull();
    fireEvent.click(pill);
    fireEvent.click(pill);
    expect(pill).toHaveAttribute("aria-expanded", "false");
  });
});
