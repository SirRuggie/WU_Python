import { describe, expect, it } from "vitest";
import {
  bonusClanCardText,
  bonusStepStates,
  type BonusStatusClan,
} from "./bonusStatus";

const clan = (patch: Partial<BonusStatusClan> = {}): BonusStatusClan => ({
  tag: "#2YQ",
  name: "Lazy One",
  active: true,
  candidates: 8,
  meets_rule: 5,
  results_state: "captured",
  allowance_ready: true,
  draw_state: "none",
  ...patch,
});

describe("clan card text", () => {
  it("shows the meet count before a draw", () => {
    expect(bonusClanCardText(clan())).toBe("5 of 8 meet · Draft");
    expect(bonusClanCardText(clan({ draw_state: "cancelled" }))).toBe(
      "5 of 8 meet · Draft",
    );
    expect(bonusClanCardText(clan({ meets_rule: null }))).toBe(
      "8 candidates · Draft",
    );
    expect(bonusClanCardText(clan({ active: false }))).toBe(
      "5 of 8 meet · Inactive",
    );
  });
  it("hides the meet count once a draw is saved, approved or sent", () => {
    expect(bonusClanCardText(clan({ draw_state: "saved" }))).toBe("Draw saved");
    expect(bonusClanCardText(clan({ draw_state: "approved" }))).toBe(
      "Approved",
    );
    expect(bonusClanCardText(clan({ draw_state: "sent" }))).toBe("Sent");
  });
});

describe("step states from the page", () => {
  const done = {
    results: true,
    rules: false,
    draw: false,
    approve: false,
    announce: false,
  };
  it("uses the page's own done map and reasons over the status read", () => {
    const steps = bonusStepStates(clan(), "lazy", 3, {
      done: { ...done, results: false },
      reasons: { results: "2 not checked · Review" },
    });
    expect(steps.map((step) => step.state)).toEqual([
      "blocked",
      "todo",
      "todo",
      "todo",
      "todo",
    ]);
    expect(steps[0].reason).toBe("2 not checked · Review");
    // With no clan in the status, the page's data still gives states.
    expect(
      bonusStepStates(null, "lazy", null, { done }).map((step) => step.state),
    ).toEqual(["done", "current", "todo", "todo", "todo"]);
  });
});
