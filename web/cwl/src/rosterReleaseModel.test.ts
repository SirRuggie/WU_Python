import { describe, expect, it } from "vitest";
import type { RosterAccount, RosterClan } from "./roster";
import {
  DEFAULT_ROSTER_RELEASE_PREFERENCES,
  deriveRosterRelease,
  orderRosterReleaseAccounts,
  parseRosterReleasePreferences,
  progressiveRosterReleaseAccounts,
  reconcileRosterSelection,
  rosterSelectionSummary,
  addAllRosterMatches,
  quickSelectRosterMatches,
  serializeRosterReleasePreferences,
  toggleRosterSelection,
  type RosterReleaseFilters,
} from "./rosterReleaseModel";

const account = (
  tag: string,
  overrides: Partial<RosterAccount> = {},
): RosterAccount => ({
  tag,
  user_id: tag.slice(1),
  pool: "main",
  player_name: tag.slice(1),
  town_hall: 16,
  prefer_crystal_1_or_lower: false,
  source_weight: 175000,
  source_status: "current",
  source_name: "fixture",
  source_checked_at: null,
  source_modified_at: null,
  manual_weight: null,
  effective_weight: 175000,
  assigned_clan_tag: null,
  kept: false,
  ...overrides,
});
const clan = (tag: string, capacity: number): RosterClan => ({
  tag,
  name: tag.slice(1),
  archived: false,
  pool: "main",
  capacity,
  effective_capacity: capacity,
  min_weight: null,
  max_weight: null,

  assigned_count: 0,
});
const accounts = [
  account("#A", {
    player_name: "Alpha",
    user_id: "1",
    effective_weight: 180000,
    town_hall: 16,
  }),
  account("#B", {
    player_name: "Beta",
    user_id: "1",
    assigned_clan_tag: "#RED",
    effective_weight: null,
    town_hall: 15,
    kept: true,
  }),
  account("#C", {
    player_name: "Charlie",
    user_id: "2",
    assigned_clan_tag: "#RED",
    effective_weight: 170000,
    town_hall: 15,
  }),
  account("#D", {
    player_name: "Delta",
    user_id: "3",
    assigned_clan_tag: "#BLUE",
    effective_weight: null,
    town_hall: 14,
    pool: "lazy",
  }),
  account("#E", {
    player_name: "Echo",
    user_id: "4",
    assigned_clan_tag: "#BLUE",
    effective_weight: 190000,
    town_hall: null,
    kept: true,
  }),
];
const clans = [clan("#RED", 1), clan("#BLUE", 2)];
const filters = (
  overrides: Partial<RosterReleaseFilters> = {},
): RosterReleaseFilters => ({
  ...DEFAULT_ROSTER_RELEASE_PREFERENCES,
  ...overrides,
});

describe("roster release filter model", () => {
  it("ORs selected statuses while ANDing other sections and using global capacity", () => {
    const result = deriveRosterRelease(
      accounts,
      clans,
      filters({
        statuses: ["unassigned", "over_capacity"],
        townHalls: [15, 16],
        pool: "main",
      }),
    );
    expect(result.matches.map((row) => row.tag)).toEqual(["#A", "#B", "#C"]);
    expect(
      deriveRosterRelease(
        accounts,
        clans,
        filters({ statuses: ["locked", "missing_weight"], pool: "main" }),
      ).matches.map((row) => row.tag),
    ).toEqual(["#B", "#E"]);
    // RED stays over capacity even when one of its accounts is filtered out.
    expect(
      deriveRosterRelease(
        accounts,
        clans,
        filters({ statuses: ["over_capacity"], search: "Charlie" }),
      ).matches.map((row) => row.tag),
    ).toEqual(["#C"]);
  });

  it("excludes missing weights from a bounded range but preserves a global missing count", () => {
    const result = deriveRosterRelease(
      accounts,
      clans,
      filters({ minWeight: 175000, maxWeight: 185000 }),
    );
    expect(result.matches.map((row) => row.tag)).toEqual(["#A"]);
    expect(result.globalMissingWeightCount).toBe(2);
    expect(result.facets.weightRangeCount).toBe(5);
    expect(
      deriveRosterRelease(
        accounts,
        clans,
        filters({ statuses: ["missing_weight"], minWeight: 1 }),
      ).matches,
    ).toEqual([]);
  });

  it("includes both 172k and 179k, excludes adjacent weights and missing", () => {
    const boundaryRows = [171999, 172000, 179000, 179001, null].map(
      (weight, index) => account(`#BOUNDARY${index}`, { effective_weight: weight }),
    );
    const result = deriveRosterRelease(
      boundaryRows,
      [],
      filters({ minWeight: 172000, maxWeight: 179000 }),
    );
    expect(result.matches.map((row) => row.effective_weight)).toEqual([172000, 179000]);
  });

  it("facets each section against every other active section", () => {
    const result = deriveRosterRelease(
      accounts,
      clans,
      filters({
        statuses: ["over_capacity"],
        townHalls: [15],
        assignedClanTags: ["#RED"],
      }),
    );
    expect(result.matches.map((row) => row.tag)).toEqual(["#B", "#C"]);
    expect(result.facets.status).toMatchObject({
      assigned: 2,
      over_capacity: 2,
      missing_weight: 1,
      locked: 1,
    });
    expect(result.facets.townHall).toEqual({ "15": 2 });
    expect(result.facets.assignedClan).toEqual({ "#RED": 2 });
    expect(result.facets.pool).toEqual({ main: 2, lazy: 0 });
    const other = deriveRosterRelease(
      accounts,
      clans,
      filters({ townHalls: [14] }),
    );
    expect(other.facets.townHall).toEqual({
      "14": 1,
      "15": 2,
      "16": 1,
      unknown: 1,
    });
  });

  it("uses assigned-clan tags rather than current location", () => {
    const moved = [
      { ...accounts[0], current_clan_tag: "#RED" },
      ...accounts.slice(1),
    ];
    expect(
      deriveRosterRelease(
        moved,
        clans,
        filters({ assignedClanTags: ["#RED"] }),
      ).matches.map((row) => row.tag),
    ).toEqual(["#B", "#C"]);
  });
});

describe("roster release ordering and progressive display", () => {
  it("defaults to unassigned then descending weight with deterministic name ties", () => {
    const rows = [
      account("#Z", {
        player_name: "Zed",
        assigned_clan_tag: "#RED",
        effective_weight: 200000,
      }),
      account("#B", { player_name: "Bee", effective_weight: 150000 }),
      account("#C", { player_name: "Cee", effective_weight: 180000 }),
      account("#A", { player_name: "Aye", effective_weight: 180000 }),
      account("#M", { player_name: "Missing", effective_weight: null }),
    ];
    expect(
      orderRosterReleaseAccounts(rows, "unassigned_first").map(
        (row) => row.tag,
      ),
    ).toEqual(["#A", "#C", "#B", "#M", "#Z"]);
    expect(
      orderRosterReleaseAccounts(rows, "weight_asc").map((row) => row.tag),
    ).toEqual(["#B", "#A", "#C", "#Z", "#M"]);
  });

  it("sorts clan, town hall and signup dates with unknown values last", () => {
    const rows = [
      account("#A", {
        assigned_clan_tag: "#Z",
        town_hall: null,
        signed_up_at: null,
      }),
      account("#B", {
        assigned_clan_tag: "#A",
        town_hall: 15,
        signed_up_at: "2026-01-02T00:00:00Z",
      }),
      account("#C", {
        assigned_clan_tag: null,
        town_hall: 17,
        signed_up_at: "2026-01-01T00:00:00Z",
      }),
    ];
    expect(
      orderRosterReleaseAccounts(rows, "assigned_clan").map((row) => row.tag),
    ).toEqual(["#B", "#A", "#C"]);
    expect(
      orderRosterReleaseAccounts(rows, "town_hall_desc").map((row) => row.tag),
    ).toEqual(["#C", "#B", "#A"]);
    expect(
      orderRosterReleaseAccounts(rows, "signed_up_asc").map((row) => row.tag),
    ).toEqual(["#C", "#B", "#A"]);
    expect(
      orderRosterReleaseAccounts(rows, "signed_up_desc").map((row) => row.tag),
    ).toEqual(["#B", "#C", "#A"]);
  });

  it("orders groups by their first sorted account and never slices a member across 50", () => {
    const rows = Array.from({ length: 49 }, (_, index) =>
      account(`#S${index}`, {
        user_id: String(index),
        effective_weight: 1000 - index,
      }),
    );
    rows.push(account("#PAIR1", { user_id: "pair", effective_weight: 950 }));
    rows.push(account("#PAIR2", { user_id: "pair", effective_weight: 1 }));
    rows.push(account("#TAIL", { user_id: "tail", effective_weight: 0 }));
    const ordered = orderRosterReleaseAccounts(rows, "weight_desc", true);
    expect(ordered.indexOf(rows[49]) + 1).toBe(ordered.indexOf(rows[50]));
    const first = progressiveRosterReleaseAccounts(ordered, 50, true);
    expect(first.visible).toHaveLength(51);
    expect(first.hasMore).toBe(true);
    expect(
      progressiveRosterReleaseAccounts(ordered, first.nextCount, true).visible,
    ).toHaveLength(52);
  });

  it("gives an oversized member its own unsplit first batch", () => {
    const rows = Array.from({ length: 51 }, (_, index) =>
      account(`#A${index}`, { user_id: "one" }),
    );
    rows.push(account("#B", { user_id: "two" }));
    const first = progressiveRosterReleaseAccounts(rows, 50, true);
    expect(first.visible).toHaveLength(51);
    expect(first.hasMore).toBe(true);
  });
});

describe("roster release selection and preferences", () => {
  it("selects all matches across batches, merges prior hidden selection, and reconciles only deleted tags", () => {
    const selected = addAllRosterMatches(["#D"], accounts.slice(0, 3))!;
    expect(selected).toEqual(["#D", "#A", "#B", "#C"]);
    expect(
      rosterSelectionSummary(
        selected,
        accounts,
        accounts.slice(0, 3),
        accounts.slice(0, 1),
      ),
    ).toMatchObject({
      selectedCount: 4,
      matchingSelectedCount: 3,
      hiddenSelectedCount: 3,
      outsideFilterSelectedCount: 1,
      staleSelectedCount: 0,
      allMatchesSelected: true,
    });
    expect(toggleRosterSelection(selected, "#A")).toEqual(["#D", "#B", "#C"]);
    expect(reconcileRosterSelection([...selected, "#GONE"], accounts)).toEqual(
      selected,
    );
    expect(
      rosterSelectionSummary(
        [...selected, "#GONE"],
        accounts,
        accounts,
        accounts,
      ).staleSelectedCount,
    ).toBe(1);
  });

  it("quick-selects unlocked accounts in the current order and replaces hidden selections", () => {
    const ordered = Array.from({ length: 34 }, (_, index) =>
      account(`#${index}`, { kept: index % 4 === 0 }),
    );
    expect(quickSelectRosterMatches(ordered, 15)).toEqual(
      ordered.filter((row) => !row.kept).slice(0, 15).map((row) => row.tag),
    );
    expect(quickSelectRosterMatches(ordered, 30)).toHaveLength(25);
    expect(quickSelectRosterMatches(ordered.slice(0, 12), 30)).toHaveLength(9);
    expect(quickSelectRosterMatches(ordered, 15)).not.toContain("#0");
  });

  it("never adds a 51st selection by checkbox or All matching", () => {
    const fifty = Array.from({ length: 50 }, (_, index) => `#${index}`);
    expect(toggleRosterSelection(fifty, "#another")).toBeNull();
    expect(toggleRosterSelection(fifty, "#0")).toHaveLength(49);
    expect(addAllRosterMatches(fifty, [account("#another")])).toBeNull();
    expect(addAllRosterMatches(["#hidden"], [account("#visible")])).toEqual([
      "#hidden",
      "#visible",
    ]);
    const fortyNine = fifty.slice(0, 49);
    const fiftieth = toggleRosterSelection(fortyNine, "#fiftieth")!;
    expect(fiftieth).toHaveLength(50);
    expect(toggleRosterSelection(fiftieth, "#fifty-first")).toBeNull();
  });

  it("validates localStorage preferences field by field and falls back safely", () => {
    expect(parseRosterReleasePreferences("{broken")).toEqual(
      DEFAULT_ROSTER_RELEASE_PREFERENCES,
    );
    const restored = parseRosterReleasePreferences(
      JSON.stringify({
        search: "a".repeat(300),
        pool: "main",
        statuses: ["locked", "bogus", "locked"],
        minWeight: 200,
        maxWeight: 100,
        townHalls: [16, -1, 16, "17"],
        assignedClanTags: ["#RED", "bad"],
        sort: "oops",
        grouped: true,
      }),
    );
    expect(restored).toMatchObject({
      pool: "main",
      statuses: ["locked"],
      minWeight: null,
      maxWeight: null,
      townHalls: [16],
      assignedClanTags: ["#RED"],
      sort: "unassigned_first",
      grouped: true,
    });
    expect(restored.search).toHaveLength(200);
    expect(
      parseRosterReleasePreferences(
        serializeRosterReleasePreferences(restored),
      ),
    ).toEqual(restored);
  });
});

it("advances past an oversized loaded group with one Load more action", () => {
  const rows = Array.from({ length: 120 }, (_, i) =>
    account(`#BIG${i}`, { user_id: "big" }),
  );
  rows.push(account("#LAST", { user_id: "last" }));
  const first = progressiveRosterReleaseAccounts(rows, 50, true);
  expect(first.visible).toHaveLength(120);
  expect(
    progressiveRosterReleaseAccounts(rows, first.nextCount, true).visible,
  ).toHaveLength(121);
});
