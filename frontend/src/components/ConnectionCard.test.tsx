import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConnectionCard } from "./ConnectionCard";
import { initialHealthState, setHealthState } from "../stores/health";

beforeEach(() => setHealthState({ ...initialHealthState }));

describe("ConnectionCard", () => {
  it("shows connecting state", () => {
    render(<ConnectionCard />);
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    expect(screen.getAllByText("Checking…")).toHaveLength(4);
  });

  it("shows connected state with services and rtt", () => {
    setHealthState({
      status: "connected",
      rttMs: 12,
      version: "0.1.0",
      services: { transcription: true, llm: false, market_data: true, email: true },
      lastCheckedAt: new Date(2026, 0, 1, 14, 2, 31).getTime(),
      retryInSec: null,
    });
    render(<ConnectionCard />);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("12 ms")).toBeInTheDocument();
    expect(screen.getByText("Response time")).toBeInTheDocument();
    expect(screen.getAllByText("Ready")).toHaveLength(3);
    expect(screen.getByText("Key missing")).toBeInTheDocument();
    expect(screen.getByText("Call analysis (AI)")).toBeInTheDocument();
    expect(screen.getByText(/Checked at 14:02:31/)).toBeInTheDocument();
  });

  it("shows offline state with countdown", () => {
    setHealthState({ ...initialHealthState, status: "offline", retryInSec: 4 });
    render(<ConnectionCard />);
    expect(screen.getByText("Can't reach Tenor's server. Trying again in 4 s.")).toBeInTheDocument();
    expect(screen.getAllByText("Not checked")).toHaveLength(4);
  });
});
