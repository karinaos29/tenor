import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { EvalScreen } from "./EvalScreen";
import { TacticsCard } from "./TacticsCard";
import { StartScreen } from "./StartScreen";
import { applyCallEvent, beginCall } from "../lib/callState";
import type { EvalReport, TacticFlag } from "../lib/events.gen";
import { useAppStore } from "../stores/app";
import { useCallStore } from "../stores/call";
import { fireEvent } from "@testing-library/react";

const ts = "2026-01-01T00:00:00Z";
const flag = (id: string, tactic: TacticFlag["tactic"], label: string, severity: TacticFlag["severity"], quote: string): TacticFlag => ({
  id, tactic, label, severity, quote, utterance_id: "u" + id, score: 0.9, source: "both",
});
const flagged = (f: TacticFlag) => ({ ts, type: "tactic.flagged" as const, flag: f });

describe("tactics state", () => {
  it("appends and resets on a new call", () => {
    const s = applyCallEvent(beginCall("mic", null), flagged(flag("1", "urgency", "A deadline", "mild", "today")), 0);
    expect(s.tactics).toHaveLength(1);
    expect(beginCall("mic", null).tactics).toEqual([]);
  });
});

describe("TacticsCard", () => {
  beforeEach(() => useCallStore.getState().reset());
  it("shows the empty state", () => {
    render(<TacticsCard />);
    expect(screen.getByText("Pressure tactics, like a deadline for today, are flagged here.")).toBeInTheDocument();
  });
  it("groups by tactic, labels severity, strong first", () => {
    const flags = [
      flag("1", "urgency", "A deadline", "mild", "first quote"),
      flag("2", "secrecy", "Keeping it secret", "strong", "keep this between us"),
      flag("3", "urgency", "A deadline", "mild", "newest quote"),
    ];
    useCallStore.setState({ tactics: flags });
    render(<TacticsCard />);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Keeping it secret");
    expect(rows[0]).toHaveTextContent("Strong");
    expect(rows[1]).toHaveTextContent("Mild");
    expect(rows[1]).toHaveTextContent("2 times");
    expect(screen.getByText(/newest quote/)).toBeInTheDocument();
    expect(screen.queryByText(/first quote/)).toBeNull();
  });
});

const m = (tactic: string, p: number) => ({ tactic, label: tactic, precision: p, recall: p, f1: p, support: 5 });
const report: EvalReport = {
  run_id: "r1", created_at: ts, commit: "abc123", note: "test run", data: "Synthetic benchmark.",
  targets: [
    { label: "T1", target: ">= 0.8", measured: "0.9", met: true },
    { label: "T2", target: ">= 0.8", measured: "0.5", met: false },
    { label: "T3", target: "n/a", measured: "-", met: null },
  ],
  detectors: [
    { name: "Tenor classifier", rows: [m("urgency", 0.9)], micro: m("all", 0.9), any_tactic: m("any", 0.95), latency_ms_median: 12, note: "Tenor note" },
    { name: "Gemini LLM", rows: [m("urgency", 0.7)], micro: m("all", 0.7), any_tactic: m("any", 0.8), latency_ms_median: 900, note: "" },
  ],
  calls: [
    { name: "scam_a", kind: "manipulative", hard_honest: false, expected: "high or critical", risk_score: 80, risk_level: "high", ok: true, false_claims_expected: 2, false_claims_caught: 2, tactic_recall: 0.8, tactic_precision: 0.9, max_visible_suggestions: 4 },
    { name: "honest_b", kind: "honest", hard_honest: true, expected: "low or medium", risk_score: 70, risk_level: "high", ok: false, false_claims_expected: 0, false_claims_caught: 0, tactic_recall: null, tactic_precision: null, max_visible_suggestions: 1 },
  ],
  latency: [], audio: false,
};

function mockFetch(impl: () => Promise<unknown>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}
afterEach(() => vi.unstubAllGlobals());

describe("EvalScreen", () => {
  it("renders targets, detectors and calls", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ report }) }));
    render(<EvalScreen />);
    expect(screen.getByText("Loading the latest evaluation…")).toBeInTheDocument();
    expect(await screen.findByText("Met")).toBeInTheDocument();
    expect(screen.getByText("Not met")).toBeInTheDocument();
    expect(screen.getByText("Not measured")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: "Tenor classifier" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gemini LLM").length).toBeGreaterThan(0);
    expect(screen.getByText("As expected")).toBeInTheDocument();
    expect(screen.getByText("Not as expected")).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
    expect(screen.getByText(/run_eval.py --audio/)).toBeInTheDocument();
  });
  it("explains a missing report", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ report: null }) }));
    render(<EvalScreen />);
    expect(await screen.findByText(/No evaluation has been run yet/)).toBeInTheDocument();
  });
  it("shows an error", async () => {
    mockFetch(async () => {
      throw new Error("down");
    });
    render(<EvalScreen />);
    expect(await screen.findByText("Couldn't load the evaluation.")).toBeInTheDocument();
  });
});

describe("Start screen reviewer link", () => {
  it("switches to the eval screen", () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ replays: [] }) }));
    useAppStore.setState({ screen: "start" });
    render(<StartScreen />);
    fireEvent.click(screen.getByRole("button", { name: "For reviewers: how Tenor is measured" }));
    expect(useAppStore.getState().screen).toBe("eval");
  });
});
