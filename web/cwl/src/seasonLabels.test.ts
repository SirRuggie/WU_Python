import { it, expect } from "vitest";
import {
  defaultStaffSeason,
  seasonCycle,
  seasonMonthLabel,
  monthSeasons,
} from "./seasonLabels";

it("uses the resolved month before exact ISO labels and preserves free labels", () => {
  expect(seasonMonthLabel({ label: "2026-08" })).toBe("August 2026");
  expect(seasonMonthLabel({ label: "2026-08", cwl_month: "2026-11" })).toBe(
    "November 2026",
  );
  expect(seasonMonthLabel({ label: "Staff <archive> & notes" })).toBe(
    "Staff <archive> & notes",
  );
  expect(seasonCycle({ label: "2026-08", cwl_month: "2026-13" })).toBe(
    "2026-08",
  );
  expect(seasonMonthLabel({ label: "2026-13" })).toBe("2026-13");
});
it("sorts newest months/higher-id ties first, free labels last, without mutation", () => {
  const input = Object.freeze([
    Object.freeze({ id: 4, label: "2026-10" }),
    Object.freeze({ id: 3, label: "2026-09" }),
    Object.freeze({ id: 2, label: "2026-08" }),
    Object.freeze({ id: 1, label: "November 2026", cwl_month: "2026-11" }),
    Object.freeze({ id: 8, label: "Old free text" }),
    Object.freeze({ id: 9, label: "Other notes" }),
    Object.freeze({
      id: 10,
      label: "Bound staff archive",
      cwl_month: "2026-11",
    }),
  ]);
  const result = monthSeasons(input);
  expect(result.map((row) => row.id)).toEqual([10, 1, 4, 3, 2, 9, 8]);
  expect(input.map((row) => row.id)).toEqual([4, 3, 2, 1, 8, 9, 10]);
  expect(result[1]).toBe(input[3]);
});

it("defaults staff to the newest normal month despite later-created imported histories, without mutation", () => {
  const seasons = Object.freeze([
    Object.freeze({ id: 4, label: "2026-10", history_only: 1 }),
    Object.freeze({ id: 3, label: "2026-09", history_only: true }),
    Object.freeze({ id: 2, label: "2026-08", history_only: 1 }),
    Object.freeze({
      id: 1,
      label: "November 2026",
      cwl_month: "2026-11",
      history_only: 0,
    }),
  ]);
  expect(defaultStaffSeason(seasons)).toBe("1");
  expect(seasons.map((row) => row.id)).toEqual([4, 3, 2, 1]);
});
it("uses newest month/higher-id tie when every season is history-only, and empty stays empty", () => {
  expect(
    defaultStaffSeason([
      { id: 9, label: "2026-08", history_only: true },
      { id: 1, label: "2026-11", history_only: 1 },
      { id: 2, label: "2026-11", history_only: true },
    ]),
  ).toBe("2");
  expect(defaultStaffSeason([])).toBe("");
});
it("excludes only true/numeric1 history and prefers an unresolvable normal label to history months", () => {
  expect(
    defaultStaffSeason([
      { id: 8, label: "2026-12", history_only: true },
      { id: 7, label: "2026-11", history_only: 1 },
      { id: 2, label: "Normal free label" },
    ]),
  ).toBe("2");
  expect(
    defaultStaffSeason([
      { id: 9, label: "2026-12", history_only: 1 },
      { id: 1, label: "2026-11", history_only: false },
      { id: 2, label: "2026-10", history_only: 0 },
    ]),
  ).toBe("1");
});
