import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { CallStrip } from "./CallStrip";
import { ClaimsCard } from "./ClaimsCard";
import { Suggestions } from "./Suggestions";
import { Transcript } from "./Transcript";
import { applyCallEvent, beginCall } from "../lib/callState";
import type { Claim, ResearchItem, Suggestion, TenorEvent } from "../lib/events.gen";
import { useCallStore } from "../stores/call";

const ts = "2026-01-01T00:00:00Z";
const claim = (id: string, status: Claim["status"], over: Partial<Claim> = {}): Claim => ({
  id, text: "It will double", metric: "price_change", claimed_value: 40, unit: "%", period: "this month",
  subject: "KSTL", utterance_id: "u1", status, actual_value: null, source: "Fixture", checked_in_ms: 12.4, note: null, ...over,
});
const sug = (id: string, over: Partial<Suggestion> = {}): Suggestion => ({
  id, kind: "say_this", title: "t", text: "Please email me the details.", priority: 1, status: "ready",
  reason: "Pressure to decide today", source: "Tenor", checked_at: null, expires_at: null, ...over,
});
const item = (id: string, over: Partial<ResearchItem> = {}): ResearchItem => ({
  id, topic: "ticker", subject: "KSTL", title: "KSTL", status: "ready", summary: "Trades under $1.",
  facts: [], source: "Fixture", checked_at: "2026-01-01T10:20:30", wording: "template", finding: null, ...over,
});
const send = (e: TenorEvent) => act(() => useCallStore.getState().dispatch(e));

beforeEach(() => useCallStore.setState({ ...beginCall("mic", null) }));

describe("reducer", () => {
  const s0 = beginCall("mic", null);
  it("upserts claims by id keeping order", () => {
    let s = applyCallEvent(s0, { ts, type: "claim.checked", claim: claim("a", "checking") }, 0);
    s = applyCallEvent(s, { ts, type: "claim.checked", claim: claim("b", "checking") }, 0);
    s = applyCallEvent(s, { ts, type: "claim.checked", claim: claim("a", "false") }, 0);
    expect(s.claims.map((c) => [c.id, c.status])).toEqual([["a", "false"], ["b", "checking"]]);
  });
  it("upserts research, replaces suggestions, sets risk, resets on new call", () => {
    let s = applyCallEvent(s0, { ts, type: "research.ready", item: item("r", { status: "prefetching" }) }, 0);
    s = applyCallEvent(s, { ts, type: "research.ready", item: item("r") }, 0);
    expect(s.research.r.status).toBe("ready");
    s = applyCallEvent(s, { ts, type: "suggestions.updated", visible: [sug("x")], earlier: [] }, 0);
    s = applyCallEvent(s, { ts, type: "suggestions.updated", visible: [sug("y")], earlier: [sug("x")] }, 0);
    expect(s.suggestions.visible.map((v) => v.id)).toEqual(["y"]);
    expect(s.suggestions.earlier).toHaveLength(1);
    s = applyCallEvent(s, { ts, type: "risk.updated", score: 55, level: "high", reasons: [] }, 0);
    expect(s.risk?.score).toBe(55);
    const fresh = beginCall("mic", null);
    expect(fresh.claims).toEqual([]);
    expect(fresh.research).toEqual({});
    expect(fresh.suggestions.visible).toEqual([]);
    expect(fresh.risk).toBeNull();
  });
});

describe("Suggestions", () => {
  it("shows say_this in quotes", () => {
    render(<Suggestions />);
    send({ ts, type: "suggestions.updated", visible: [sug("a")], earlier: [] });
    expect(screen.getByText("“Please email me the details.”")).toBeInTheDocument();
    expect(screen.getByText("Say this")).toBeInTheDocument();
  });
  it("never renders more than 4", () => {
    render(<Suggestions />);
    send({ ts, type: "suggestions.updated", visible: ["1", "2", "3", "4", "5"].map((i) => sug(i, { text: `line ${i}` })), earlier: [] });
    expect(screen.getAllByText("Say this")).toHaveLength(4);
    expect(screen.queryByText("“line 5”")).toBeNull();
  });
  it("shows prefetching vs ready research", () => {
    render(<Suggestions />);
    send({ ts, type: "suggestions.updated", visible: [sug("r1", { kind: "research", status: "prefetching", title: "KSTL" })], earlier: [] });
    expect(screen.getByText("Research · prefetching")).toBeInTheDocument();
    expect(screen.getByText("Prefetching…")).toBeInTheDocument();
    send({ ts, type: "research.ready", item: item("r1") });
    send({ ts, type: "suggestions.updated", visible: [sug("r1", { kind: "research", status: "ready", title: "KSTL", checked_at: "2026-01-01T10:20:30" })], earlier: [] });
    expect(screen.getByText("Research · ready")).toBeInTheDocument();
    expect(screen.getByText("Trades under $1.")).toBeInTheDocument();
    expect(screen.getByText(/Source: Fixture · checked/)).toBeInTheDocument();
  });
});

describe("ClaimsCard", () => {
  it("shows empty state, then each status label, false first", () => {
    render(<ClaimsCard />);
    expect(screen.getByText("Claims the caller makes are checked against market data here.")).toBeInTheDocument();
    for (const [i, st] of (["verified", "unverifiable", "not_found", "false"] as const).entries()) {
      send({ ts, type: "claim.checked", claim: claim(`c${i}`, st, st === "false" ? { actual_value: -12, note: "last 13 weeks" } : {}) });
    }
    send({ ts, type: "claim.checked", claim: claim("pending", "checking") });
    const labels = ["Doesn't match data", "No evidence found", "Matches data", "Couldn't verify"];
    const found = screen.getAllByText((t) => labels.includes(t)).map((e) => e.textContent);
    expect(found).toEqual(["Doesn't match data", "No evidence found", "Matches data", "Couldn't verify"]);
    expect(screen.getByText("Doesn't match data").closest("li")?.textContent).toContain("Data: -12% (last 13 weeks)");
  });
});

describe("risk pill", () => {
  it.each([["low", "Low"], ["medium", "Medium"], ["high", "High"], ["critical", "Critical"]] as const)("labels %s", (level, label) => {
    render(<CallStrip />);
    send({ ts, type: "risk.updated", score: 70, level, reasons: [{ label: "A claim doesn't match data", points: 30 }] });
    const pill = screen.getByText(new RegExp(`· ${label}$`));
    expect(pill).toBeInTheDocument();
    fireEvent.click(pill);
    expect(screen.getByText("A claim doesn't match data")).toBeInTheDocument();
  });
});

describe("transcript chip", () => {
  it("marks a caller line that has a checked claim", () => {
    render(<Transcript />);
    send({ ts, type: "utterance.final", utterance: { id: "u1", speaker: "caller", speaker_index: 0, text: "It will double", t_start: 0, t_end: 1, is_final: true } });
    send({ ts, type: "claim.checked", claim: claim("c", "false") });
    expect(screen.getByText("Doesn't match data")).toBeInTheDocument();
  });
});
