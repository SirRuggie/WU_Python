import { describe, it, expect } from "vitest";
import {
  comparisonAge,
  comparisonLocation,
  comparisonTally,
  mergeComparisonLocations,
  type ComparisonLocation,
} from "./comparisonLocation";
const now = Date.parse("2026-10-27T12:00:00Z");
const location: ComparisonLocation = {
  current_clan_tag: "#A",
  current_clan_name: "Clan A",
  current_clan_checked_at: new Date(now).toISOString(),
  current_clan_status: "current",
  outside_family: true,
};
describe("last-known comparison locations", () => {
  it("keeps red and green regardless of age, updating or stale status", () => {
    for (const minutes of [0, 3, 6, 11, 65]) {
      const record = {
        ...location,
        arrival_status: "unknown",
        location_updating: true,
      };
      expect(
        comparisonLocation(record, "#A", now + minutes * 60000).state,
      ).toBe("arrived");
      expect(
        comparisonLocation(record, "#B", now + minutes * 60000).state,
      ).toBe("missing");
      expect(
        comparisonLocation(record, "#A", now + minutes * 60000).detail,
      ).not.toContain("Location unknown");
    }
    expect(comparisonAge(now, now + 65 * 60000)).toBe("1h 5m ago");
  });
  it("uses Checking only before the first result, and no clan means elsewhere", () => {
    expect(comparisonLocation(undefined, "#A", now)).toEqual({
      state: "checking",
      label: "Checking…",
      detail: "Checking…",
    });
    expect(
      comparisonLocation(
        { ...location, current_clan_tag: null, current_clan_name: null },
        "#A",
        now,
      ),
    ).toMatchObject({ state: "missing", detail: "No clan · just now" });
  });
  it("accepts only newer records and only verified outside-family flags", () => {
    const old = { "#P": location };
    expect(mergeComparisonLocations(old, [])).toEqual(old);
    expect(
      mergeComparisonLocations(old, [
        { ...location, tag: "#P", current_clan_tag: "#B" },
      ]),
    ).toEqual(old);
    const stale = {
      ...location,
      tag: "#P",
      current_clan_checked_at: new Date(now + 1000).toISOString(),
      current_clan_status: "stale",
      outside_family: false,
    };
    expect(mergeComparisonLocations(old, [stale])["#P"].outside_family).toBe(
      true,
    );
    expect(
      mergeComparisonLocations(old, [
        { ...stale, current_clan_status: "current" },
      ])["#P"].outside_family,
    ).toBe(false);
    expect(
      mergeComparisonLocations(old, [
        { ...stale, current_clan_checked_at: undefined },
      ]),
    ).toEqual(old);
  });
  it("counts all assigned tags, including no-clan and checking separately", () => {
    expect(
      comparisonTally(
        ["a", "b", "c", "d"],
        {
          a: location,
          b: { ...location, current_clan_tag: "#B" },
          c: { ...location, current_clan_tag: null, outside_family: false },
        },
        "#A",
      ),
    ).toEqual({ arrived: 1, elsewhere: 2, checking: 1, outside: 2 });
  });
});
