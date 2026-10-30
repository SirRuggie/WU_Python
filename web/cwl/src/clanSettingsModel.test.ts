import { expect, it } from "vitest";
import {
  capacityState,
  rangeImpact,
  settingsWeight,
  weightKeystroke,
} from "./clanSettingsModel";
import { comparisonWeightRange } from "./comparePresentation";
import type { RosterAccount } from "./roster";
it("accepts only digits and a single decimal point, with exact 0.001k precision", () => {
  for (const value of ["1e3", "-1", "+1", "1.2.3", " "])
    expect(weightKeystroke(value)).toBe(false);
  for (const value of ["", "1", "1.", ".5", "174.001"])
    expect(weightKeystroke(value)).toBe(true);
  expect(settingsWeight("174.001")).toEqual({ value: 174001, error: "" });
  expect(settingsWeight("1.0001").error).not.toBe("");
  expect(settingsWeight("1000000.001").error).not.toBe("");
  expect(settingsWeight("0").error).toBe(
    "Enter a weight above 0, or leave blank for no limit.",
  );
  expect(settingsWeight("")).toEqual({ value: null, error: "" });
});
it("shares all four Compare range wordings and capacity states", () => {
  expect(
    comparisonWeightRange({ min_weight: 150000, max_weight: 170000 }),
  ).toBe("150k–170k");
  expect(comparisonWeightRange({ min_weight: 150000, max_weight: null })).toBe(
    "150k+",
  );
  expect(comparisonWeightRange({ min_weight: null, max_weight: 170000 })).toBe(
    "up to 170k",
  );
  expect(
    comparisonWeightRange({ min_weight: null, max_weight: null }) ||
      "Any weight",
  ).toBe("Any weight");
  expect(capacityState(16, 15)).toBe("over");
  expect(capacityState(15, 15)).toBe("full");
  expect(capacityState(14, 15)).toBe("room");
  expect(capacityState(14, null)).toBe("room");
});
it("counts only assigned, known weights outside inclusive min and max", () => {
  const accounts = [149999, 150000, 169999, 170000, 170001, null].map(
    (effective_weight, index) => ({
      tag: String(index),
      assigned_clan_tag: "A",
      effective_weight,
    }),
  ) as RosterAccount[];
  accounts.push({
    tag: "other",
    assigned_clan_tag: "B",
    effective_weight: 190000,
  } as RosterAccount);
  expect(rangeImpact(accounts, "A", 150000, 170000).map((a) => a.tag)).toEqual([
    "0",
    "4",
  ]);
  expect(rangeImpact(accounts, "A", null, null)).toEqual([]);
});
