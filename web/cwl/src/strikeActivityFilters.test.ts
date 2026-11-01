import { expect, it } from "vitest";
import {
  activitySorts,
  activitySortLabels,
  activityViewCounts,
  activityViewPreset,
  activityFilterQuery,
  parseActivityFilters,
  visibleActivityAccounts,
  appliedActivityFilters,
  clearActivityFilters,
  copyActivityList,
} from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";
const row = (patch: Partial<ActivityAccount> = {}): ActivityAccount => ({
  player_tag: "#PYY",
  player_name: "Ada",
  active_strikes: 3,
  total_strikes: 3,
  marked_for_replacement: false,
  status: "active",
  quiet_days: 20,
  last_seen_at: "2026-10-01T00:00:00Z",
  observed_wars: 14,
  no_attack_wars: 5,
  attacked_wars: 4,
  missed_attacks: 20,
  observed_attacks: 28,
  skipped_raid_weekends: 2,
  observed_raid_weekends: 2,
  attacked_raid_weekends: 0,
  tracking_started_at: "2026-09-01T00:00:00Z",
  town_hall: 18,
  weight: 160000,
  current_clan_tag: "#P2Y",
  current_clan_name: "Amber",
  priority: "high",
  last_attacked_war_end: "2026-10-10T00:00:00Z",
  ...patch,
});
it("opens Not attacking with an explicit known-war filter and preserves replacements aliases", () => {
  const f = parseActivityFilters();
  expect(f.view).toBe("not_attacking");
  expect(f.noAttackMin).toBe(3);
  expect(f.sort).toBe("wars");
  expect(parseActivityFilters("", true).view).toBe("replacements");
  expect(parseActivityFilters("?marked=1").marked).toBe(true);
  expect(parseActivityFilters("?view=all").noAttackMin).toBe(0);
});
it("unknown and contradictory war samples never count as missed wars", () => {
  const rows = [
    row(),
    row({ player_tag: "#PQQ", observed_wars: undefined, no_attack_wars: 14 }),
    row({ player_tag: "#PYQ", observed_wars: 0, no_attack_wars: 14 }),
    row({ player_tag: "#PYP", observed_wars: 2, no_attack_wars: 14 }),
    row({ player_tag: "#PYR", activity_unavailable: true }),
  ];
  expect(
    visibleActivityAccounts(rows, parseActivityFilters()).map(
      (r) => r.player_tag,
    ),
  ).toEqual(["#PYY"]);
  expect(activityViewCounts(rows).not_attacking).toBe(1);
});
it("round-trips every visible filter, direction and pagination, ignoring removed API status", () => {
  const f = {
    ...parseActivityFilters("?view=all"),
    query: "Name & Tag",
    clans: ["#P2Y", "#Q2Y"],
    marked: true,
    includeLow: true,
    noAttackMin: 10 as const,
    quietMin: 30 as const,
    raidMin: 2 as const,
    strikeMode: "new_this_week" as const,
    priorities: ["high", "none"] as const,
    townHalls: [16, 18],
    minWeight: 150000,
    maxWeight: 170000,
    left: "left" as const,
    noActivity: true,
    sort: "last_attack" as const,
    direction: "asc" as const,
    page: 3,
  };
  const normalized = { ...f, priorities: [...f.priorities] };
  expect(parseActivityFilters(activityFilterQuery(normalized))).toEqual(
    normalized,
  );
  expect(parseActivityFilters("?view=all&status=risk")).toEqual(
    parseActivityFilters("?view=all"),
  );
});
it.each(activitySorts)(
  "sort %s has a matching label, works both directions and leaves unknown last",
  (sort) => {
    const a = row({
        player_name: "A",
        player_tag: "#PYY",
        no_attack_wars: 3,
        quiet_days: 5,
        active_strikes: 1,
        weight: 150000,
        town_hall: 16,
        missed_attacks: 2,
        skipped_raid_weekends: 0,
        attacked_raid_weekends: 2,
        priority: "normal",
        current_clan_name: "A",
        last_attacked_war_end: "2026-10-01T00:00:00Z",
      }),
      b = row({ player_name: "B", player_tag: "#PQQ" });
    expect(activitySortLabels[sort]).toBeTruthy();
    const asc = visibleActivityAccounts([b, a], {
      ...parseActivityFilters("?view=all"),
      sort,
      direction: "asc",
    });
    const desc = visibleActivityAccounts([a, b], {
      ...parseActivityFilters("?view=all"),
      sort,
      direction: "desc",
    });
    expect(asc[0].player_tag).toBe("#PYY");
    expect(desc[0].player_tag).toBe("#PQQ");
    if (!["name", "clan", "priority", "strikes"].includes(sort)) {
      const unknown = row({
        player_tag: "#PRR",
        observed_wars: undefined,
        last_seen_at: null,
        quiet_days: null,
        weight: null,
        town_hall: null,
        last_attacked_war_end: null,
        observed_raid_weekends: undefined,
      });
      expect(
        visibleActivityAccounts([unknown, a], {
          ...parseActivityFilters("?view=all"),
          sort,
          direction: "asc",
        }).at(-1)?.player_tag,
      ).toBe("#PRR");
    }
  },
);
it("combines every filter and lists each predicate that can change bulk membership", () => {
  const f = {
    ...parseActivityFilters("?view=all"),
    query: "Ada",
    clans: ["#P2Y"],
    marked: true,
    includeLow: true,
    noAttackMin: 5 as const,
    quietMin: 14 as const,
    raidMin: 2 as const,
    strikeMode: "3" as const,
    priorities: ["high" as const],
    townHalls: [18],
    minWeight: 159000,
    maxWeight: 161000,
    left: "left" as const,
  };
  const matching = row({
    marked_for_replacement: true,
    left_clan: true,
    last_clan_tag: "#P2Y",
  });
  expect(
    visibleActivityAccounts(
      [matching, row({ player_tag: "#PQQ", marked_for_replacement: false })],
      f,
    ),
  ).toEqual([matching]);
  const chips = appliedActivityFilters(f, [{ tag: "#P2Y", name: "Amber" }]);
  expect(chips.map((c) => c.key).sort()).toEqual(
    [
      "query",
      "clans",
      "marked",
      "wars",
      "quiet",
      "raids",
      "strikes",
      "priority",
      "th",
      "weight",
      "left",
    ].sort(),
  );
  expect(chips.find((c) => c.key === "marked")?.label).toContain("eligible");
  expect(clearActivityFilters(f).view).toBe("all");
  expect(
    visibleActivityAccounts([matching, row()], clearActivityFilters(f)),
  ).toHaveLength(2);
});
it("view shortcuts expose their predicates and clear incompatible tab state", () => {
  let f = activityViewPreset(parseActivityFilters("?view=all"), "inactive");
  expect(f.quietMin).toBe(14);
  expect(appliedActivityFilters(f).some((c) => c.key === "quiet")).toBe(true);
  f = activityViewPreset(f, "not_attacking");
  expect(f.quietMin).toBe(0);
  expect(f.noAttackMin).toBe(3);
  expect(parseActivityFilters("?view=not_attacking&wars=0").view).toBe(
    "not_attacking",
  );
});
it("replacement eligibility and include-low rules stay unchanged", () => {
  const rows = [
    row({ marked_for_replacement: true }),
    row({
      player_tag: "#PQQ",
      active_strikes: 2,
      replacement_eligible_low: true,
    }),
    row({
      player_tag: "#PRR",
      active_strikes: 2,
      replacement_eligible_low: false,
    }),
  ];
  const f = parseActivityFilters("", true);
  expect(visibleActivityAccounts(rows, f)).toHaveLength(1);
  expect(
    visibleActivityAccounts(rows, { ...f, includeLow: true }),
  ).toHaveLength(2);
});
it("All14 requires fourteen known wars and inactivity never invents missing dates", () => {
  expect(
    visibleActivityAccounts(
      [
        row({ no_attack_wars: 14 }),
        row({ player_tag: "#PQQ", observed_wars: 5, no_attack_wars: 5 }),
      ],
      parseActivityFilters("?view=all&wars=14"),
    ),
  ).toHaveLength(1);
  expect(
    visibleActivityAccounts(
      [row({ quiet_days: 66, last_seen_at: null })],
      parseActivityFilters("?view=inactive"),
    ),
  ).toHaveLength(0);
});
it("copies all matching rows on one line each and neutralizes external mentions", () => {
  const rows = Array.from({ length: 65 }, (_, i) =>
    row({
      player_name: i ? "Name " + i : "@everyone\n<@123>",
      player_tag: "#P" + i,
    }),
  );
  const copy = copyActivityList(rows);
  expect(copy.split("\n")).toHaveLength(65);
  expect(copy).toContain("@\u200beveryone <@\u200b123> #P0");
  expect(copy.split("\n").at(-1)).toBe("Name 64 #P64");
});

it("sort labels describe exactly the selected numeric or text value", () => {
  expect(activitySorts.map((key) => activitySortLabels[key])).toEqual([
    "Wars without attacking",
    "Quiet days",
    "Last attack (war end)",
    "Strikes",
    "Weight",
    "Town hall",
    "Missed attacks",
    "Skipped raids",
    "Priority",
    "Name",
    "Clan",
  ]);
});

it("unobserved or contradictory raid samples never satisfy a missed-weekend filter", () => {
  const filters = {
    ...parseActivityFilters("?activity_view=all"),
    raidMin: 1 as const,
  };
  expect(
    visibleActivityAccounts(
      [
        row({ observed_raid_weekends: undefined }),
        row({ observed_raid_weekends: 0 }),
        row({ attacked_raid_weekends: 2 }),
      ],
      filters,
    ),
  ).toEqual([]);
  expect(visibleActivityAccounts([row()], filters)).toHaveLength(1);
});
it("keeps the selected tab while clearing additional filters and restores legacy marked=0", () => {
  const f = parseActivityFilters(
    "?activity_view=not_attacking&q=Someone&clans=%23PYY",
  );
  const clear = clearActivityFilters(f);
  expect(clear.view).toBe("not_attacking");
  expect(clear.noAttackMin).toBe(3);
  expect(clear.query).toBe("");
  expect(clear.clans).toEqual([]);
  expect(parseActivityFilters("?marked=0").view).toBe("all");
});
it("extra chain filters narrow All and the Not attacking tab", () => {
  const rows = [
    row({ no_attack_wars: 3 }),
    row({ no_attack_wars: 5 }),
    row({ no_attack_wars: 10 }),
  ];
  for (const view of ["all", "not_attacking"]) {
    const f = parseActivityFilters(`?activity_view=${view}&wars=5`);
    expect(
      visibleActivityAccounts(rows, f)
        .map((r) => r.no_attack_wars)
        .sort((a, b) => a! - b!),
    ).toEqual([5, 10]);
  }
});
