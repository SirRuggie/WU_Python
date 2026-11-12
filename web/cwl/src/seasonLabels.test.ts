import { it, expect } from "vitest";
import { seasonCycle, seasonMonthLabel, monthSeasons } from "./seasonLabels";

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
