import { expect, it } from "vitest";
import { nextMonthCycle } from "./seasonLabels";

const now = new Date("2026-07-15T00:00:00Z");

it("uses the newest cycle label", () => {
  expect(
    nextMonthCycle([{ label: "2026-10" }, { label: "2026-11" }], now),
  ).toBe("2026-12");
});
it("reads Month YYYY labels and the resolved month", () => {
  expect(nextMonthCycle([{ label: "November 2026" }], now)).toBe("2026-12");
  expect(nextMonthCycle([{ label: "Notes", cwl_month: "2026-12" }], now)).toBe(
    "2027-01",
  );
});
it("falls back to the month after the current UTC month", () => {
  expect(nextMonthCycle([{ label: "Free text" }], now)).toBe("2026-08");
  expect(nextMonthCycle([], new Date("2026-12-31T23:00:00Z"))).toBe("2027-01");
});
