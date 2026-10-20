import { describe, expect, it } from "vitest";
import { highlightSegments, offerPhrasesFor } from "./highlight";
import type { Offer, Term } from "./events.gen";

describe("highlightSegments", () => {
  it("matches case-insensitively and keeps original casing", () => {
    expect(highlightSegments("Buy TEN thousand now", ["ten thousand"])).toEqual([
      { text: "Buy ", mark: false },
      { text: "TEN thousand", mark: true },
      { text: " now", mark: false },
    ]);
  });
  it("marks several and repeated matches", () => {
    const segs = highlightSegments("a 42 cents, 42 cents", ["42 cents"]);
    expect(segs.filter((s) => s.mark)).toHaveLength(2);
    expect(segs.map((s) => s.text).join("")).toBe("a 42 cents, 42 cents");
  });
  it("keeps the earliest of overlapping matches", () => {
    const segs = highlightSegments("ten thousand shares", ["ten thousand", "thousand shares"]);
    expect(segs.filter((s) => s.mark).map((s) => s.text)).toEqual(["ten thousand"]);
    expect(segs.map((s) => s.text).join("")).toBe("ten thousand shares");
  });
  it("returns plain text when nothing matches", () => {
    expect(highlightSegments("hello", ["xyz", ""])).toEqual([{ text: "hello", mark: false }]);
  });
});

describe("offerPhrasesFor", () => {
  const term = (said: string, utterance_id: string | null): Term => ({
    display: "x", number: null, said, utterance_id, t: null, confidence: "heard", source: "call",
  });
  it("collects current and historic phrases for one utterance", () => {
    const offer = {
      caller_name: null, firm: null, instrument: null, price: term("42 cents", "u1"), quantity: term("ten thousand", "u2"),
      total: null, fees: null, deadline: null, payment: null,
      history: [{ field: "quantity", old: term("five thousand", "u1"), new: term("ten thousand", "u2") }],
    } as Offer;
    expect(offerPhrasesFor(offer, "u1").sort()).toEqual(["42 cents", "five thousand"]);
    expect(offerPhrasesFor(null, "u1")).toEqual([]);
  });
});
