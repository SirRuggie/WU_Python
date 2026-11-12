import { describe, expect, it } from "vitest";
import { rosterResultSummary } from "./exportPreview";

describe("season exports", () => {
  it("keeps results from another assignment out of roster preview totals", () => {
    expect(
      rosterResultSummary(
        {
          participation_matches_roster: false,
          participation_recorded_clan_name: "Old Host",
        },
        "participation_",
      ),
    ).toBe("Recorded for another assignment: Old Host");
    expect(
      rosterResultSummary({ matches_roster: true, attacks: 5, stars: 12 }),
    ).toBe("5 attacks · 12 stars");
  });
});

it("keeps compact preview formatting separate from the unchanged input", async () => {
  const { exportMonthLabel, exportWeightLabel } = await import(
    "./exportPreview"
  );
  const row = { effective_weight: 179000, cycle: "2026-11" };
  expect(exportWeightLabel(row.effective_weight)).toBe("179k");
  expect(exportWeightLabel(null)).toBe("—");
  expect(exportMonthLabel(row.cycle)).toBe("November 2026");
  expect(exportMonthLabel("Custom saved month")).toBe("Custom saved month");
  expect(row).toEqual({ effective_weight: 179000, cycle: "2026-11" });
});
