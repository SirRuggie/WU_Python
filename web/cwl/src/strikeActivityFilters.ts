/** Account-list view rules. API status is deliberately ignored here. */
import type { ActivityAccount, ActivityPriority } from "./strikeActivityView";
export const activityViews = [
  "not_attacking",
  "inactive",
  "replacements",
  "all",
] as const;
export type ActivityView = (typeof activityViews)[number];
export const activitySorts = [
  "wars",
  "quiet",
  "last_attack",
  "strikes",
  "weight",
  "th",
  "missed",
  "raids",
  "priority",
  "name",
  "clan",
] as const;
export type ActivitySort = (typeof activitySorts)[number];
export const activitySortLabels: Record<ActivitySort, string> = {
  wars: "Wars without attacking",
  quiet: "Quiet days",
  last_attack: "Last attack (war end)",
  strikes: "Strikes",
  weight: "Weight",
  th: "Town hall",
  missed: "Missed attacks",
  raids: "Skipped raids",
  priority: "Priority",
  name: "Name",
  clan: "Clan",
};
export type ActivityFilters = {
  view: ActivityView;
  query: string;
  clans: string[];
  marked: boolean;
  includeLow: boolean;
  noAttackMin: 0 | 3 | 5 | 10 | 14;
  quietMin: 0 | 7 | 14 | 30;
  raidMin: 0 | 1 | 2;
  strikeMode: "any" | "1" | "3" | "over_limit" | "new_this_week";
  priorities: (ActivityPriority | "none")[];
  townHalls: number[];
  minWeight: number | null;
  maxWeight: number | null;
  left: "all" | "left" | "current";
  noActivity: boolean;
  sort: ActivitySort;
  direction: "asc" | "desc";
  page: number;
};
export const activityFilterKeys = [
  "activity_view",
  "q",
  "clans",
  "marked",
  "low",
  "wars",
  "quiet",
  "raids",
  "strikes",
  "priority",
  "th",
  "min_weight",
  "max_weight",
  "left",
  "no_activity",
  "sort",
  "direction",
  "page",
  "status",
  "action",
];
export const count = (value: unknown): number | null =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  Number.isInteger(value) &&
  value >= 0
    ? value
    : null;
const positive = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : null;
const text = (value: string | null | undefined) => value?.trim() || null;
export function knownWars(row: ActivityAccount) {
  const total = count(row.observed_wars);
  return !row.activity_unavailable && total !== null && total > 0
    ? total
    : null;
}
export function warsWithoutAttacking(row: ActivityAccount) {
  const total = knownWars(row),
    missed = count(row.no_attack_wars);
  return total !== null && missed !== null && missed <= total ? missed : null;
}
export function quietDays(row: ActivityAccount) {
  return row.activity_unavailable ||
    row.activity_tracking_behind ||
    !row.last_seen_at ||
    !Number.isFinite(Date.parse(row.last_seen_at))
    ? null
    : count(row.quiet_days);
}
export function knownRaidMisses(row: ActivityAccount) {
  const total = count(row.observed_raid_weekends),
    attacked = count(row.attacked_raid_weekends),
    missed = count(row.skipped_raid_weekends);
  return !row.activity_unavailable &&
    total !== null &&
    total > 0 &&
    total <= 2 &&
    attacked !== null &&
    attacked <= total &&
    missed === total - attacked
    ? missed
    : null;
}
export function hasNoActivity(row: ActivityAccount) {
  return (
    !row.activity_unavailable && !row.last_seen_at && !!row.tracking_started_at
  );
}
const tags = (value: string | null) => [
  ...new Set(
    (value || "")
      .split(",")
      .filter((tag) => /^#[0289PYLQGRJCUV]{3,15}$/.test(tag)),
  ),
];
const threshold = <T extends number>(
  value: string | null,
  choices: readonly T[],
  fallback: T,
): T =>
  value !== null && value !== "" && choices.includes(Number(value) as T)
    ? (Number(value) as T)
    : fallback;
const range = (value: string | null) =>
  value !== null &&
  value !== "" &&
  Number.isFinite(Number(value)) &&
  Number(value) >= 0 &&
  Number(value) <= 10_000_000
    ? Number(value)
    : null;
export function normalizeActivityView(value: ActivityFilters): ActivityFilters {
  let view = value.view;
  if (
    (view === "not_attacking" && value.noAttackMin < 3) ||
    (view === "inactive" && value.quietMin < 14) ||
    (view === "replacements" && !value.marked)
  )
    view = "all";
  return { ...value, view };
}
export function parseActivityFilters(
  search = "",
  markedDefault = false,
): ActivityFilters {
  const p = new URLSearchParams(search);
  const requested = p.get("activity_view") || p.get("view");
  const view: ActivityView = activityViews.includes(requested as ActivityView)
    ? (requested as ActivityView)
    : markedDefault || p.get("marked") === "1"
      ? "replacements"
      : "not_attacking";
  const sort = p.get("sort");
  const defaultSort: ActivitySort =
    view === "not_attacking"
      ? "wars"
      : view === "inactive"
        ? "quiet"
        : view === "replacements"
          ? "priority"
          : "name";
  const selectedSort = activitySorts.includes(sort as ActivitySort)
    ? (sort as ActivitySort)
    : defaultSort;
  const legacy = p.get("action");
  const mode = p.get("strikes") || legacy;
  return normalizeActivityView({
    view,
    query: (p.get("q") || "").slice(0, 80),
    clans: tags(p.get("clans")),
    marked: p.has("marked") ? p.get("marked") === "1" : view === "replacements",
    includeLow: p.get("low") === "1",
    noAttackMin: threshold(
      p.get("wars"),
      [0, 3, 5, 10, 14] as const,
      view === "not_attacking" ? 3 : 0,
    ),
    quietMin: threshold(
      p.get("quiet"),
      [0, 7, 14, 30] as const,
      view === "inactive" ? 14 : 0,
    ),
    raidMin: threshold(p.get("raids"), [0, 1, 2] as const, 0),
    strikeMode: ["1", "3", "over_limit", "new_this_week"].includes(mode || "")
      ? (mode as ActivityFilters["strikeMode"])
      : "any",
    priorities: [
      ...new Set(
        (p.get("priority") || "")
          .split(",")
          .filter((v): v is ActivityFilters["priorities"][number] =>
            ["replace_first", "high", "normal", "none"].includes(v),
          ),
      ),
    ],
    townHalls: [
      ...new Set(
        (p.get("th") || "")
          .split(",")
          .map(Number)
          .filter((v) => Number.isInteger(v) && v > 0 && v <= 99),
      ),
    ],
    minWeight: range(p.get("min_weight")),
    maxWeight: range(p.get("max_weight")),
    left:
      p.get("left") === "left" || p.get("left") === "1"
        ? "left"
        : p.get("left") === "current"
          ? "current"
          : "all",
    noActivity: p.get("no_activity") === "1",
    sort: selectedSort,
    direction:
      p.get("direction") === "asc" || p.get("direction") === "desc"
        ? (p.get("direction") as "asc" | "desc")
        : ["name", "clan"].includes(selectedSort)
          ? "asc"
          : "desc",
    page: Math.min(
      999,
      Math.max(
        0,
        Number.isInteger(Number(p.get("page"))) ? Number(p.get("page")) : 0,
      ),
    ),
  });
}
export function activityFilterQuery(f: ActivityFilters) {
  const p = new URLSearchParams();
  p.set("activity_view", f.view);
  if (f.query) p.set("q", f.query);
  if (f.clans.length) p.set("clans", [...f.clans].sort().join(","));
  p.set("marked", f.marked ? "1" : "0");
  if (f.includeLow) p.set("low", "1");
  p.set("wars", String(f.noAttackMin));
  p.set("quiet", String(f.quietMin));
  if (f.raidMin) p.set("raids", String(f.raidMin));
  if (f.strikeMode !== "any") p.set("strikes", f.strikeMode);
  if (f.priorities.length)
    p.set("priority", [...f.priorities].sort().join(","));
  if (f.townHalls.length)
    p.set("th", [...f.townHalls].sort((a, b) => a - b).join(","));
  if (f.minWeight !== null) p.set("min_weight", String(f.minWeight));
  if (f.maxWeight !== null) p.set("max_weight", String(f.maxWeight));
  if (f.left !== "all") p.set("left", f.left);
  if (f.noActivity) p.set("no_activity", "1");
  p.set("sort", f.sort);
  p.set("direction", f.direction);
  if (f.page) p.set("page", String(f.page));
  return p.toString();
}
export function activityViewPreset(
  f: ActivityFilters,
  view: ActivityView,
): ActivityFilters {
  return {
    ...f,
    view,
    noAttackMin: view === "not_attacking" ? 3 : 0,
    quietMin: view === "inactive" ? 14 : 0,
    marked: view === "replacements",
    sort:
      view === "not_attacking"
        ? "wars"
        : view === "inactive"
          ? "quiet"
          : view === "replacements"
            ? "priority"
            : "name",
    direction: view === "all" ? "asc" : "desc",
    page: 0,
  };
}
export function clearActivityFilters(f: ActivityFilters): ActivityFilters {
  return {
    ...parseActivityFilters("?view=all"),
    sort: f.sort,
    direction: f.direction,
  };
}
export function replacementMatches(row: ActivityAccount, includeLow: boolean) {
  return (
    row.marked_for_replacement ||
    (includeLow &&
      row.replacement_eligible_low !== false &&
      row.active_strikes > 0 &&
      row.active_strikes < 3)
  );
}
const priorityRank = { replace_first: 3, high: 2, normal: 1 };
export function activitySortValue(
  row: ActivityAccount,
  sort: ActivitySort,
): number | string | null {
  switch (sort) {
    case "wars":
      return warsWithoutAttacking(row);
    case "quiet":
      return quietDays(row);
    case "last_attack": {
      if (row.activity_unavailable) return null;
      const at =
        row.last_attacked_war_end && Date.parse(row.last_attacked_war_end);
      return typeof at === "number" && Number.isFinite(at) ? at : null;
    }
    case "strikes":
      return count(row.active_strikes);
    case "weight":
      return positive(row.weight);
    case "th":
      return positive(row.town_hall);
    case "missed":
      return knownWars(row) !== null ? count(row.missed_attacks) : null;
    case "raids":
      return knownRaidMisses(row);
    case "priority":
      return row.priority ? priorityRank[row.priority] : 0;
    case "name":
      return text(row.player_name);
    case "clan":
      return text(row.left_clan ? row.last_clan_name : row.current_clan_name);
  }
}
export function visibleActivityAccounts(
  rows: ActivityAccount[],
  f: ActivityFilters,
) {
  const search = f.query.trim().normalize("NFKC").toLocaleLowerCase();
  return rows
    .filter((row) => {
      const wars = warsWithoutAttacking(row),
        quiet = quietDays(row),
        raids = knownRaidMisses(row),
        strikes = count(row.active_strikes),
        weight = positive(row.weight);
      return (
        (!search ||
          [
            row.player_name,
            row.player_tag,
            row.discord_id,
            row.discord_name,
          ].some((value) =>
            value?.normalize("NFKC").toLocaleLowerCase().includes(search),
          )) &&
        (!f.clans.length ||
          f.clans.includes(
            (row.left_clan ? row.last_clan_tag : row.current_clan_tag) || "",
          )) &&
        (!f.marked || replacementMatches(row, f.includeLow)) &&
        (!f.noAttackMin ||
          (wars !== null &&
            wars >= f.noAttackMin &&
            (f.noAttackMin !== 14 || knownWars(row) === 14))) &&
        (!f.quietMin || (quiet !== null && quiet >= f.quietMin)) &&
        (!f.raidMin || (raids !== null && raids >= f.raidMin)) &&
        (f.strikeMode === "any" ||
          (f.strikeMode === "over_limit" && row.over_limit) ||
          (f.strikeMode === "new_this_week" && row.new_this_week) ||
          (f.strikeMode === "1" && strikes !== null && strikes >= 1) ||
          (f.strikeMode === "3" && strikes !== null && strikes >= 3)) &&
        (!f.priorities.length ||
          f.priorities.includes(row.priority || "none")) &&
        (!f.townHalls.length || f.townHalls.includes(row.town_hall || 0)) &&
        (f.minWeight === null || (weight !== null && weight >= f.minWeight)) &&
        (f.maxWeight === null || (weight !== null && weight <= f.maxWeight)) &&
        (f.left === "all" || (f.left === "left") === !!row.left_clan) &&
        (!f.noActivity || hasNoActivity(row))
      );
    })
    .sort((a, b) => {
      const av = activitySortValue(a, f.sort),
        bv = activitySortValue(b, f.sort);
      if (av === null && bv !== null) return 1;
      if (bv === null && av !== null) return -1;
      let order =
        av === null || bv === null
          ? 0
          : typeof av === "string" && typeof bv === "string"
            ? av.localeCompare(bv, undefined, { sensitivity: "base" })
            : Number(av) - Number(bv);
      if (f.direction === "desc") order = -order;
      if (!order && f.sort === "wars")
        order = b.active_strikes - a.active_strikes;
      return (
        order ||
        a.player_name.localeCompare(b.player_name) ||
        a.player_tag.localeCompare(b.player_tag)
      );
    });
}
export function activityViewCounts(
  rows: ActivityAccount[],
  includeLow = false,
) {
  return Object.fromEntries(
    activityViews.map((view) => {
      const f = activityViewPreset(parseActivityFilters("?view=all"), view);
      f.includeLow = includeLow;
      return [view, visibleActivityAccounts(rows, f).length];
    }),
  ) as Record<ActivityView, number>;
}
export function copyActivityList(rows: ActivityAccount[]) {
  return rows
    .map(
      (row) =>
        `${row.player_name.replace(/[\r\n\t]+/g, " ").replace(/@/g, "@\u200b")} ${row.player_tag}`,
    )
    .join("\n");
}
export type AppliedActivityFilter = {
  key: string;
  label: string;
  clear: Partial<ActivityFilters>;
};
export function appliedActivityFilters(
  f: ActivityFilters,
  clans: { tag: string; name: string }[] = [],
): AppliedActivityFilter[] {
  const result: AppliedActivityFilter[] = [];
  const add = (key: string, label: string, clear: Partial<ActivityFilters>) =>
    result.push({ key, label, clear });
  if (f.query) add("query", `Search: ${f.query}`, { query: "" });
  if (f.noAttackMin)
    add(
      "wars",
      f.noAttackMin === 14
        ? "No attacks in all 14 known wars"
        : `No attacks in last ${f.noAttackMin}+ known wars`,
      { noAttackMin: 0 },
    );
  if (f.quietMin) add("quiet", `Quiet ${f.quietMin}+ days`, { quietMin: 0 });
  if (f.raidMin) add("raids", `Skipped ${f.raidMin}+ raids`, { raidMin: 0 });
  if (f.marked)
    add(
      "marked",
      f.includeLow
        ? "Marked or eligible with 1–2 strikes"
        : "Marked replacements",
      { marked: false, includeLow: false },
    );
  if (f.strikeMode !== "any")
    add(
      "strikes",
      f.strikeMode === "over_limit"
        ? "Over limit"
        : f.strikeMode === "new_this_week"
          ? "New this week"
          : `${f.strikeMode}+ strikes`,
      { strikeMode: "any" },
    );
  if (f.priorities.length)
    add(
      "priority",
      `Priority: ${f.priorities.map((p) => (p === "replace_first" ? "Chopping Block" : p === "high" ? "High" : p === "normal" ? "Normal" : "None")).join(", ")}`,
      { priorities: [] },
    );
  if (f.townHalls.length)
    add("th", `TH ${f.townHalls.join(", ")}`, { townHalls: [] });
  if (f.minWeight !== null || f.maxWeight !== null)
    add("weight", `Weight ${f.minWeight ?? "any"}–${f.maxWeight ?? "any"}`, {
      minWeight: null,
      maxWeight: null,
    });
  if (f.clans.length)
    add(
      "clans",
      f.clans
        .map((tag) => clans.find((c) => c.tag === tag)?.name || tag)
        .join(", "),
      { clans: [] },
    );
  if (f.left !== "all")
    add("left", f.left === "left" ? "Left clan" : "Current clan", {
      left: "all",
    });
  if (f.noActivity)
    add("no_activity", "No activity yet", { noActivity: false });
  return result;
}
