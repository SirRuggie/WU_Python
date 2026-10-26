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
  // Keep delivery/check failures as the primary health state. Destination
  // inventory is displayed separately so it cannot hide an uncertain send.
  if (row.health.category === "attention") return row.health;
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
export function destinationIssue(
  row: OverviewRow,
  channels: Set<string>,
  available: boolean,
): string | null {
  if (!row.settings.enabled || !row.settings.channel_id || !available)
    return null;
  if (channels.has(row.settings.channel_id)) return null;
  return "Saved channel is missing from the current server channel list. It may have been removed or become inaccessible.";
}

export function deliveryLabel(status: string): string {
  switch (status) {
    case "sent": return "Sent";
    case "sending":
    case "uncertain":
      return "Unconfirmed; check the channel before acting";
    case "failed": return "Failed";
    case "skipped": return "Skipped";
    default: return status;
  }
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
