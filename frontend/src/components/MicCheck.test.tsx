import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { initialMicState, useMicStore } from "../stores/mic";
import { MicCheck } from "./MicCheck";

beforeEach(() => {
  useMicStore.setState({ ...initialMicState, permission: "granted" });
});

describe("voice check at the mic check", () => {
  it("asks for a sentence and shows how much it has heard", () => {
    useMicStore.setState({ voice: "listening", voiceProgress: 0.5 });
    render(<MicCheck />);
    expect(screen.getByText(/Now say a sentence/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Voice check" })).toHaveAttribute("aria-valuenow", "50");
  });

  it("says when Tenor knows the voice", () => {
    useMicStore.setState({ voice: "ready", voiceId: "v1" });
    render(<MicCheck />);
    expect(screen.getByText("Tenor knows your voice")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("explains a failure and offers to try again", () => {
    useMicStore.setState({ voice: "failed", voiceMessage: "Tenor couldn't hear enough. Say a full sentence, then try again." });
    render(<MicCheck />);
    expect(screen.getByText(/couldn't hear enough/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try the voice check again" })).toBeInTheDocument();
  });
});
