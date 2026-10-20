import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { OfferCard } from "./OfferCard";
import { CallStrip } from "./CallStrip";
import { beginCall } from "../lib/callState";
import type { Offer, Term } from "../lib/events.gen";
import { useCallStore } from "../stores/call";

const term = (display: string, over: Partial<Term> = {}): Term => ({
  display, number: null, said: "", utterance_id: null, t: null, confidence: "heard", source: "call", ...over,
});
const emptyOffer: Offer = {
  caller_name: null, firm: null, instrument: null, price: null, quantity: null,
  total: null, fees: null, deadline: null, payment: null, history: [],
};
const setOffer = (o: Partial<Offer>) =>
  act(() => useCallStore.getState().dispatch({ ts: "2026-01-01T00:00:00Z", type: "offer.updated", offer: { ...emptyOffer, ...o } }));

beforeEach(() => useCallStore.setState({ ...beginCall("mic", null) }));

describe("OfferCard", () => {
  it("shows the empty state until a term exists", () => {
    render(<OfferCard />);
    expect(screen.getByText("Terms fill in as the caller states them.")).toBeInTheDocument();
    setOffer({ caller_name: term("Dan") });
    expect(screen.getByText("Terms fill in as the caller states them.")).toBeInTheDocument();
  });

  it("shows rows with a source line", () => {
    render(<OfferCard />);
    setOffer({ price: term("$0.42 a share", { t: 24 }), instrument: term("KSTL · Kestrel Motors", { t: 10 }) });
    expect(screen.getByText("Investment")).toBeInTheDocument();
    expect(screen.getByText("$0.42 a share")).toBeInTheDocument();
    expect(screen.getByText("said at 0:24")).toBeInTheDocument();
    expect(screen.queryByText("Quantity")).toBeNull();
  });

  it("shows the previous value from history", () => {
    render(<OfferCard />);
    const q = term("10,000 shares", { t: 60 });
    setOffer({ quantity: q, history: [{ field: "quantity", old: term("5,000"), new: q }] });
    expect(screen.getByText("(was 5,000)")).toBeInTheDocument();
  });

  it("explains a computed total", () => {
    render(<OfferCard />);
    setOffer({ total: term("$4,200", { source: "computed" }) });
    expect(screen.getByText("price × quantity")).toBeInTheDocument();
  });

  it("flags an unsure term", () => {
    render(<OfferCard />);
    setOffer({ price: term("$0.42 a share", { confidence: "unsure", t: 5 }) });
    expect(screen.getByText("$0.42 a share?")).toBeInTheDocument();
    expect(screen.getByText("Not sure we heard this right")).toBeInTheDocument();
  });
});

describe("CallStrip caller", () => {
  it("shows name · firm, and the hint only while both are null", () => {
    render(<CallStrip />);
    expect(screen.getByText("Name and firm fill in as the caller says them")).toBeInTheDocument();
    setOffer({ caller_name: term("Dan Reyes"), firm: term("Northgate Capital") });
    expect(screen.getByText("Dan Reyes · Northgate Capital")).toBeInTheDocument();
    expect(screen.queryByText("Name and firm fill in as the caller says them")).toBeNull();
  });
});
