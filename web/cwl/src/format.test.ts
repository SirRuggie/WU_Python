import { describe, expect, it } from "vitest";
import {
  formatCycleMonth,
  formatDate,
  formatDateTime,
  formatNumber,
  formatTime,
} from "./format";

describe("format helpers", () => {
  it("groups numbers with en-US regardless of viewer locale", () => {
    expect(formatNumber(35800)).toBe("35,800");
    expect(formatNumber(35.8, { maximumFractionDigits: 3 })).toBe("35.8");
    expect(formatNumber(1234567)).toBe("1,234,567");
  });

  it("formats dates and times with explicit options", () => {
    const value = "2026-03-04T15:30:00Z";
    const date = new Date(value);
    expect(formatDateTime(value)).toBe(
      new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date),
    );
    expect(formatDate(date)).toBe(
      new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date),
    );
    expect(formatTime(date.getTime())).toBe(
      new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(date),
    );
  });

  it("reads cycle months in UTC", () => {
    expect(formatCycleMonth("2026-04")).toMatch(/Apr/);
    expect(formatCycleMonth("2026-01", "short")).toMatch(/2026/);
  });
});
