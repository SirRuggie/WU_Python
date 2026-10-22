import { describe, expect, it } from "vitest";
import {
  normalizeArrivalAccount,
  summarizeArrivalReadiness,
  type ArrivalAccount,
} from "./arrivalReadiness";

const now = Date.parse("2026-10-22T12:00:00Z");
const checkedAt = new Date(now).toISOString();

function assigned(tag: string, overrides: Partial<ArrivalAccount> = {}): ArrivalAccount {
  return {
    tag,
    assigned_clan_tag: "#HOST",
    arrival_status: "arrived",
    current_clan_checked_at: checkedAt,
    ...overrides,
  };
}

describe("arrival readiness", () => {
  it("normalizes missing, invalid, stale, and in-flight checks to unknown", () => {
    const cases = [
      assigned("#MISSING", { current_clan_checked_at: undefined }),
      assigned("#INVALID", { current_clan_checked_at: "not a date" }),
      assigned("#STALE", { current_clan_checked_at: new Date(now - 120_001).toISOString() }),
      assigned("#UPDATING", { location_updating: true }),
    ];
    expect(cases.map((account) => normalizeArrivalAccount(account, now).arrival_status)).toEqual([
      "unknown", "unknown", "unknown", "unknown",
    ]);
  });

  it("preserves unassigned status even without a location check", () => {
    const account = assigned("#UNASSIGNED", {
      assigned_clan_tag: null,
      arrival_status: "unassigned",
      current_clan_checked_at: undefined,
      outside_family: true,
    });
    expect(normalizeArrivalAccount(account, now)).toEqual(account);
  });

  it("is ready only with at least 15 assigned accounts all confirmed arrived", () => {
    const fifteen = Array.from({ length: 15 }, (_, index) => assigned(`#P${index}`));
    expect(summarizeArrivalReadiness(fifteen.slice(0, 14), { now }).ready).toBe(false);
    expect(summarizeArrivalReadiness(fifteen, { now })).toMatchObject({
      assignedCount: 15,
      arrivedCount: 15,
      unknownCount: 0,
      ready: true,
    });
    expect(summarizeArrivalReadiness([
      ...fifteen.slice(0, 14),
      assigned("#WAITING", { arrival_status: "unknown" }),
    ], { now }).ready).toBe(false);
    expect(summarizeArrivalReadiness([
      ...fifteen.slice(0, 14),
      assigned("#MISSING", { arrival_status: "missing" }),
    ], { now }).ready).toBe(false);
  });

  it.each([
    ["loading", { loading: true }],
    ["an error", { error: true }],
    ["an outdated publication", { outdated: true }],
  ])("is not ready during %s", (_label, blocker) => {
    const fifteen = Array.from({ length: 15 }, (_, index) => assigned(`#P${index}`));
    expect(summarizeArrivalReadiness(fifteen, { now, ...blocker }).ready).toBe(false);
  });

  it("ignores unassigned accounts when counting readiness", () => {
    const assignedAccounts = Array.from({ length: 15 }, (_, index) => assigned(`#P${index}`));
    const unassigned = assigned("#UNASSIGNED", {
      assigned_clan_tag: null,
      arrival_status: "unassigned",
    });
    expect(summarizeArrivalReadiness([...assignedAccounts, unassigned], { now }).ready).toBe(true);
  });
});
