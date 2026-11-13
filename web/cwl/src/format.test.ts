import { describe, expect, it } from "vitest";
import {
  formatCycleMonth,
  formatDate,
  formatDateTime,
  formatNumber,
  formatTime,
} from "./format";

const pinned = { locale: "en-US", timeZone: "UTC" };
const value = "2026-03-04T15:30:45Z";

describe("format helpers", () => {
  it("groups numbers with en-US regardless of viewer locale", () => {
    expect(formatNumber(35800)).toBe("35,800");
    expect(formatNumber(35.8, { maximumFractionDigits: 3 })).toBe("35.8");
    expect(formatNumber(1234567)).toBe("1,234,567");
  });

  it("formats dates and times with explicit options", () => {
    expect(formatDateTime(value, pinned)).toBe("Mar 4, 2026, 3:30 PM");
    expect(formatDateTime(value, { ...pinned, seconds: true })).toBe(
      "Mar 4, 2026, 3:30:45 PM",
    );
    expect(formatDate(new Date(value), pinned)).toBe("Mar 4, 2026");
    expect(formatTime(Date.parse(value), pinned)).toBe("3:30 PM");
    expect(formatDateTime(value, { locale: "en-GB", timeZone: "UTC" })).toBe(
      "4 Mar 2026, 15:30",
    );
  });

  it.each([null, undefined, "", "not a date", Number.NaN, new Date("x")])(
    "returns a dash for unreadable input %p without throwing",
    (input) => {
      expect(formatDateTime(input)).toBe("—");
      expect(formatDateTime(input, { seconds: true })).toBe("—");
      expect(formatDate(input)).toBe("—");
      expect(formatTime(input)).toBe("—");
    },
  );

  it("reads cycle months in UTC", () => {
    expect(formatCycleMonth("2026-04")).toMatch(/Apr/);
    expect(formatCycleMonth("2026-01", "short")).toMatch(/2026/);
  });
});
