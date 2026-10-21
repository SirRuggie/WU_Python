import type { Clan } from "./types";
import type { ReminderSettings } from "../warReminders/types";
export type Health = {
  category: "attention" | "pending" | "tracking" | "off" | "not_configured";
  label: string;
  detail: string;
};
export type OverviewRow = {
  clan: Clan;
  settings: ReminderSettings;
  health: Health;
  checked_at: string | null;
  last_delivery: { at: string; status: string; event: string } | null;
};
export type OverviewData = { clans: OverviewRow[]; generated_at: string };
export type OverviewFilter = "all" | "attention" | "enabled" | "off";
export function rowHealth(
  row: OverviewRow,
  channels: Set<string>,
  available: boolean,
): Health {
  if (
    row.settings.enabled &&
    available &&
    !channels.has(row.settings.channel_id)
  )
    return {
      category: "attention",
      label: "Channel unavailable",
      detail:
        "The saved channel is missing from the current server channel list. Review the destination.",
    };
  return row.health;
}
export function visibleRows(
  rows: OverviewRow[],
  query: string,
  filter: OverviewFilter,
  channels: Map<string, string>,
  available: boolean,
) {
  const ids = new Set(channels.keys()),
    term = query.trim().toLowerCase();
  return rows
    .filter(
      (row) =>
        (filter === "all" ||
          (filter === "attention" &&
            rowHealth(row, ids, available).category === "attention") ||
          (filter === "enabled" && row.settings.enabled) ||
          (filter === "off" && !row.settings.enabled)) &&
        `${row.clan.name} ${row.clan.tag} ${row.clan.type} ${channels.get(row.settings.channel_id) || ""} ${row.settings.channel_id}`
          .toLowerCase()
          .includes(term),
    )
    .sort(
      (a, b) =>
        Number(rowHealth(b, ids, available).category === "attention") -
          Number(rowHealth(a, ids, available).category === "attention") ||
        a.clan.name.localeCompare(b.clan.name) ||
        a.clan.tag.localeCompare(b.clan.tag),
    );
}
