import { it, expect } from "vitest";
import {
  activityChips,
  activityFilterQuery,
  parseActivityFilters,
  visibleActivityAccounts,
  activityCounts,
  type ActivityAccount,
} from "./strikeActivityView";
const healthy: ActivityAccount = {
  player_tag: "#PYY",
  player_name: "Healthy",
  active_strikes: 0,
  total_strikes: 0,
  marked_for_replacement: false,
  status: "active",
  quiet_days: 0,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  skipped_raid_weekends: 0,
};
it("healthy has exactly one green activity chip and unknown never claims Quiet", () => {
  expect(activityChips(healthy)).toEqual([
    { label: "Active today", tone: "good" },
  ]);
  const unknown = activityChips({
    ...healthy,
    quiet_days: null,
    last_seen_at: null,
    tracking_started_at: "2026-11-01T00:00:00Z",
  });
  expect(unknown).toEqual([
    { label: "Not seen since tracking began (Nov 1)", tone: "neutral" },
  ]);
});
it.each([2, 3, 13, 14])("quiet chip boundary %s", (days) => {
  const chips = activityChips({ ...healthy, quiet_days: days });
  expect(chips.some((chip) => chip.label.startsWith("Quiet"))).toBe(days >= 3);
  if (days >= 3) expect(chips[0].tone).toBe(days >= 14 ? "bad" : "warn");
});
it("filters and URL round-trip including replacements alias and explicit clearing", () => {
  expect(parseActivityFilters("", true).marked).toBe(true);
  const filters = {
    ...parseActivityFilters(),
    query: "name & tag",
    clans: ["#PQQ", "#PYY"],
    statuses: ["risk" as const],
    marked: true,
    includeLow: true,
    townHalls: [16, 17],
    left: "left" as const,
    sort: "weight" as const,
    page: 2,
  };
  expect(parseActivityFilters(activityFilterQuery(filters))).toEqual(filters);
  expect(
    parseActivityFilters(
      activityFilterQuery({ ...filters, marked: false }),
      true,
    ).marked,
  ).toBe(false);
});
it("client filtering sorting and counts apply to the current filtered rows", () => {
  const risk = {
    ...healthy,
    player_tag: "#PQQ",
    player_name: "Risk",
    status: "risk" as const,
    active_strikes: 3,
    marked_for_replacement: true,
    weight: 149000,
  };
  const watch = {
    ...healthy,
    player_tag: "#PRR",
    player_name: "Watch",
    status: "watch" as const,
    active_strikes: 1,
    weight: 100000,
  };
  const filters = parseActivityFilters();
  expect(
    visibleActivityAccounts([healthy, watch, risk], filters).map(
      (row) => row.player_name,
    ),
  ).toEqual(["Risk", "Watch", "Healthy"]);
  const marked = visibleActivityAccounts([healthy, watch, risk], {
    ...filters,
    marked: true,
  });
  expect(marked).toEqual([risk]);
  expect(activityCounts(marked)).toEqual({ risk: 1, watch: 0, active: 0 });
  expect(
    visibleActivityAccounts([healthy, watch, risk], {
      ...filters,
      marked: true,
      includeLow: true,
    }),
  ).toEqual([risk, watch]);
});

it("unavailable and stale activity never renders Quiet or invented activity", () => {
  expect(
    activityChips({
      ...healthy,
      activity_unavailable: true,
      quiet_days: 20,
      missed_attacks: 4,
    }),
  ).toEqual([{ label: "Activity unavailable", tone: "neutral" }]);
  const stale = activityChips({
    ...healthy,
    activity_tracking_behind: true,
    quiet_days: 20,
  });
  expect(
    stale.some((chip) => chip.label === "Activity tracking is behind"),
  ).toBe(true);
  expect(
    stale.some(
      (chip) =>
        chip.label.includes("Quiet") || chip.label.includes("Not seen since"),
    ),
  ).toBe(false);
});

it("restores action filters and priority ties use strikes then weight", () => {
  const a = {
    ...healthy,
    player_tag: "#P22",
    player_name: "Alpha",
    priority: "high" as const,
    active_strikes: 1,
    weight: 150000,
    over_limit: false,
    new_this_week: true,
  };
  const b = {
    ...a,
    player_tag: "#P33",
    player_name: "Beta",
    active_strikes: 3,
    weight: 140000,
    over_limit: true,
    new_this_week: false,
  };
  const c = { ...b, player_tag: "#P44", player_name: "Zebra", weight: 160000 };
  expect(
    visibleActivityAccounts(
      [a, b, c],
      parseActivityFilters("?sort=priority"),
    ).map((row) => row.player_tag),
  ).toEqual([c.player_tag, b.player_tag, a.player_tag]);
  expect(
    visibleActivityAccounts([a, b], parseActivityFilters("?action=over_limit")),
  ).toEqual([b]);
  expect(
    visibleActivityAccounts(
      [a, b],
      parseActivityFilters("?action=new_this_week"),
    ),
  ).toEqual([a]);
  expect(
    parseActivityFilters(
      activityFilterQuery(parseActivityFilters("?action=new_this_week")),
    ).action,
  ).toBe("new_this_week");
});

it("Include 1–2 strikes respects the owner's explicit low eligibility", () => {
  const row = {
    ...healthy,
    active_strikes: 1,
    replacement_eligible_low: false,
  };
  expect(
    visibleActivityAccounts([row], {
      ...parseActivityFilters(),
      marked: true,
      includeLow: true,
    }),
  ).toEqual([]);
});


it("keeps the Left clan chip while activity is unavailable", () => {
  const labels = activityChips({...healthy, left_clan:true, activity_unavailable:true,
    quiet_days:40}).map(chip => chip.label);
  expect(labels).toContain("Left clan");
  expect(labels.some(label => label.startsWith("Quiet"))).toBe(false);
});
