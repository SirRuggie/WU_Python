export type ActivityStatus = "risk" | "watch" | "active";
export type ActivityPriority = "replace_first" | "high" | "normal";
export type ActivityAccount = {
  player_tag: string;
  revision?: number;
  over_limit?: boolean;
  new_this_week?: boolean;
  player_name: string;
  current_clan_tag?: string | null;
  current_clan_name?: string | null;
  last_clan_tag?: string | null;
  last_clan_name?: string | null;
  left_clan?: boolean;
  town_hall?: number | null;
  weight?: number | null;
  active_strikes: number;
  total_strikes: number;
  discord_id?: string | null;
  discord_name?: string | null;
  priority?: ActivityPriority | null;
  marked_for_replacement: boolean;
  replacement_eligible_low?: boolean;
  departed_at?: string | null;
  status: ActivityStatus;
  quiet_days: number | null;
  activity_unavailable?: boolean;
  activity_tracking_behind?: boolean;
  replacement_note?: string;
  last_seen_at?: string | null;
  last_seen_source?: string | null;
  tracking_started_at?: string | null;
  missed_attacks: number;
  observed_attacks: number;
  no_attack_wars: number;
  observed_wars?: number | null;
  attacked_wars?: number | null;
  last_attacked_war_end?: string | null;
  observed_raid_weekends?: number | null;
  attacked_raid_weekends?: number | null;
  skipped_raid_weekends: number;
};
export const activitySorts = [
  "status",
  "quiet",
  "strikes",
  "weight",
  "th",
  "missed",
  "name",
  "priority",
] as const;
export type ActivitySort = (typeof activitySorts)[number];
export type ActivityFilters = {
  action: "all" | "over_limit" | "new_this_week";
  query: string;
  clans: string[];
  statuses: ActivityStatus[];
  marked: boolean;
  includeLow: boolean;
  onlyStrikes: boolean;
  townHalls: number[];
  left: "all" | "left" | "current";
  sort: ActivitySort;
  page: number;
};
export const activityFilterKeys = [
  "action",
  "q",
  "clans",
  "status",
  "marked",
  "low",
  "strikes",
  "th",
  "left",
  "sort",
  "page",
];
const tags = (value: string | null) => [
  ...new Set(
    (value || "")
      .split(",")
      .filter((tag) => /^#[0289PYLQGRJCUV]{3,15}$/.test(tag)),
  ),
];
export function parseActivityFilters(
  search = "",
  markedDefault = false,
): ActivityFilters {
  const params = new URLSearchParams(search);
  const sort = params.get("sort");
  const left = params.get("left");
  return {
    action:
      params.get("action") === "over_limit" ||
      params.get("action") === "new_this_week"
        ? (params.get("action") as ActivityFilters["action"])
        : "all",
    query: (params.get("q") || "").slice(0, 80),
    clans: tags(params.get("clans")),
    statuses: (params.get("status") || "")
      .split(",")
      .filter((value): value is ActivityStatus =>
        ["risk", "watch", "active"].includes(value),
      ),
    marked: params.has("marked") ? params.get("marked") === "1" : markedDefault,
    includeLow: params.get("low") === "1",
    onlyStrikes: params.get("strikes") === "1",
    townHalls: [
      ...new Set(
        (params.get("th") || "")
          .split(",")
          .map(Number)
          .filter(
            (value) => Number.isInteger(value) && value > 0 && value <= 99,
          ),
      ),
    ],
    left: left === "left" || left === "current" ? left : "all",
    sort: activitySorts.includes(sort as ActivitySort)
      ? (sort as ActivitySort)
      : "status",
    page: Math.min(
      999,
      Math.max(
        0,
        Number.isInteger(Number(params.get("page")))
          ? Number(params.get("page"))
          : 0,
      ),
    ),
  };
}
export function activityFilterQuery(filters: ActivityFilters) {
  const params = new URLSearchParams();
  if (filters.action !== "all") params.set("action", filters.action);
  if (filters.query) params.set("q", filters.query);
  if (filters.clans.length)
    params.set("clans", [...filters.clans].sort().join(","));
  if (filters.statuses.length)
    params.set("status", [...filters.statuses].sort().join(","));
  params.set("marked", filters.marked ? "1" : "0");
  if (filters.includeLow) params.set("low", "1");
  if (filters.onlyStrikes) params.set("strikes", "1");
  if (filters.townHalls.length)
    params.set("th", [...filters.townHalls].sort((a, b) => a - b).join(","));
  if (filters.left !== "all") params.set("left", filters.left);
  if (filters.sort !== "status") params.set("sort", filters.sort);
  if (filters.page) params.set("page", String(filters.page));
  return params.toString();
}
export const activityStatusLabels = {
  risk: "At risk",
  watch: "Watch",
  active: "Active",
};
export const activityPriorityLabels = {
  replace_first: "Chopping Block",
  high: "High priority",
  normal: "Normal priority",
};
export type ActivityChip = {
  label: string;
  tone: "bad" | "warn" | "good" | "neutral";
};
export function activityChips(row: ActivityAccount): ActivityChip[] {
  const chips: ActivityChip[] = [];
  if (row.activity_unavailable)
    chips.push({ label: "Activity unavailable", tone: "neutral" });
  const seed = row.last_seen_source === "clashking_seed" ? " (ClashKing)" : "";
  if (!row.activity_unavailable) {
    if (row.left_clan) {
      // Membership is the status; departure is never inactivity evidence.
    } else if (row.activity_tracking_behind) {
      chips.push({ label: "Activity tracking is behind", tone: "neutral" });
    } else if (row.quiet_days === null || !row.last_seen_at) {
      const date = row.tracking_started_at && new Date(row.tracking_started_at);
      const label =
        date && Number.isFinite(date.getTime())
          ? ` (${date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })})`
          : "";
      chips.push({
        label: `Not seen since tracking began${label}`,
        tone: "neutral",
      });
    } else if (row.quiet_days >= 3)
      chips.push({
        label: `Quiet for ${row.quiet_days} days${seed}`,
        tone: row.quiet_days >= 14 ? "bad" : "warn",
      });
    if (row.missed_attacks > 0)
      chips.push({
        label: `Missed ${row.missed_attacks} of ${row.observed_attacks} war attacks`,
        tone: "warn",
      });
    if (row.no_attack_wars > 0)
      chips.push({
        label: `Didn't attack in their last ${row.no_attack_wars} ${row.no_attack_wars === 1 ? "war" : "wars"}`,
        tone: "bad",
      });
    if (row.skipped_raid_weekends > 0)
      chips.push({
        label: `Skipped the last ${row.skipped_raid_weekends} raid ${row.skipped_raid_weekends === 1 ? "weekend" : "weekends"}`,
        tone: "warn",
      });
  }
  if (row.priority)
    chips.push({
      label: activityPriorityLabels[row.priority],
      tone: row.priority === "replace_first" ? "bad" : "warn",
    });
  if (row.over_limit) chips.push({ label: "Over limit", tone: "bad" });
  if (row.new_this_week) chips.push({ label: "New this week", tone: "warn" });
  if (row.left_clan) chips.push({ label: "Left clan", tone: "neutral" });
  if (!chips.length)
    chips.push({
      label:
        row.quiet_days === 0
          ? `Active today${seed}`
          : `Active ${row.quiet_days} ${row.quiet_days === 1 ? "day" : "days"} ago${seed}`,
      tone: "good",
    });
  return chips;
}
export function visibleActivityAccounts(
  rows: ActivityAccount[],
  filters: ActivityFilters,
) {
  const search = filters.query.toLocaleLowerCase();
  const statusRank = { risk: 0, watch: 1, active: 2 };
  const priorityRank = { replace_first: 0, high: 1, normal: 2 };
  return rows
    .filter(
      (row) =>
        (!search ||
          [
            row.player_name,
            row.player_tag,
            row.discord_id,
            row.discord_name,
          ].some((value) => value?.toLocaleLowerCase().includes(search))) &&
        (!filters.clans.length ||
          filters.clans.includes(
            (row.left_clan ? row.last_clan_tag : row.current_clan_tag) || "",
          )) &&
        (!filters.statuses.length || filters.statuses.includes(row.status)) &&
        (filters.action === "all" ||
          (filters.action === "over_limit"
            ? row.over_limit
            : row.new_this_week)) &&
        (!filters.onlyStrikes || row.active_strikes > 0) &&
        (!filters.marked ||
          row.marked_for_replacement ||
          (filters.includeLow &&
            row.replacement_eligible_low !== false &&
            row.active_strikes > 0 &&
            row.active_strikes < 3)) &&
        (!filters.townHalls.length ||
          filters.townHalls.includes(row.town_hall || 0)) &&
        (filters.left === "all" ||
          (filters.left === "left") === !!row.left_clan),
    )
    .sort((a, b) => {
      const numeric = (
        key:
          | "quiet_days"
          | "active_strikes"
          | "weight"
          | "town_hall"
          | "missed_attacks",
      ) => (b[key] ?? -1) - (a[key] ?? -1);
      const order =
        filters.sort === "status"
          ? statusRank[a.status] - statusRank[b.status] ||
            numeric("active_strikes")
          : filters.sort === "quiet"
            ? numeric("quiet_days")
            : filters.sort === "strikes"
              ? numeric("active_strikes")
              : filters.sort === "weight"
                ? numeric("weight")
                : filters.sort === "th"
                  ? numeric("town_hall")
                  : filters.sort === "missed"
                    ? numeric("missed_attacks")
                    : filters.sort === "priority"
                      ? (a.priority ? priorityRank[a.priority] : 3) -
                          (b.priority ? priorityRank[b.priority] : 3) ||
                        numeric("active_strikes") ||
                        numeric("weight")
                      : 0;
      return (
        order ||
        a.player_name.localeCompare(b.player_name) ||
        a.player_tag.localeCompare(b.player_tag)
      );
    });
}
export function activityCounts(rows: ActivityAccount[]) {
  return {
    risk: rows.filter((row) => row.status === "risk").length,
    watch: rows.filter((row) => row.status === "watch").length,
    active: rows.filter((row) => row.status === "active").length,
  };
}
