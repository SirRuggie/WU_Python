import { describe, expect, it } from "vitest";
import {
  activeRosterFilterCount,
  clearRosterFiltersPreservingPool,
} from "./RosterFilters";
import { DEFAULT_ROSTER_RELEASE_PREFERENCES } from "./rosterReleaseModel";

describe("roster filter controls", () => {
  it("counts every active removable filter and clears them without changing the pool", () => {
    const selected = {
      ...DEFAULT_ROSTER_RELEASE_PREFERENCES,
      pool: "lazy" as const,
      search: "alpha",
      statuses: [
        "assigned",
        "locked",
      ] as typeof DEFAULT_ROSTER_RELEASE_PREFERENCES.statuses,
      minWeight: 150000,
      maxWeight: 190000,
      townHalls: [15, 16],
      assignedClanTags: ["#ONE"],
    };
    expect(activeRosterFilterCount(selected)).toBe(7);
    expect(clearRosterFiltersPreservingPool(selected)).toEqual({
      ...DEFAULT_ROSTER_RELEASE_PREFERENCES,
      pool: "lazy",
      statuses: [],
      townHalls: [],
      assignedClanTags: [],
    });
    expect(selected.statuses).toEqual(["assigned", "locked"]);
  });
});
