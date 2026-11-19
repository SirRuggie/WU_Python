import type { Clan } from "./types";
import { timeLabel, type ReminderSettings } from "../warReminders/types";
import { clanCategory } from "./ClanCategories";
export type Health = {
  category:
    | "attention"
    | "pending"
    | "tracking"
    | "off"
    | "not_configured"
    | "maintenance";
  label: string;
  detail: string;
};
export type OverviewRow = {
  clan: Clan;
  settings: ReminderSettings;
  revision: string;
  health: Health;
  checked_at: string | null;
  last_delivery: { at: string; status: string; event: string } | null;
};
export type OverviewData = { clans: OverviewRow[]; generated_at: string };
export type OverviewFilter =
  "all" | "attention" | "enabled" | "off" | "not_set_up";
/** On and Off both have a saved channel; a row without one is not set up. */
export const notSetUp = (row: OverviewRow) => !row.settings.channel_id;
export function scheduleSummary(settings: ReminderSettings): string {
  const parts: string[] = [];
  if (settings.war_started) parts.push("War start");
  if (settings.minutes.length)
    parts.push(
      `${settings.minutes.slice(0, 3).map(timeLabel).join(", ")} before end${
        settings.minutes.length > 3
          ? ` · +${settings.minutes.length - 3} more`
          : ""
      }`,
    );
  return parts.join(" · ") || "No times selected";
}
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
  return "The saved channel is not in the server channel list. Someone may have removed it, or Discord may not allow reminders there.";
}

export function deliveryLabel(status: string): string {
  switch (status) {
    case "sent":
      return "Sent";
    case "sending":
    case "uncertain":
      return "Unconfirmed; check the channel before acting";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    default:
      return status;
  }
}
export function visibleRows(
  rows: OverviewRow[],
  query: string,
  filter: OverviewFilter,
  channels: Map<string, string>,
  available: boolean,
  category = "",
) {
  const ids = new Set(channels.keys()),
    term = query.trim().toLowerCase();
  return rows
    .filter(
      (row) =>
        (!category || clanCategory(row.clan.type) === category) &&
        (filter === "all" ||
          (filter === "attention" &&
            rowHealth(row, ids, available).category === "attention") ||
          (filter === "enabled" && row.settings.enabled) ||
          (filter === "off" && !row.settings.enabled && !notSetUp(row)) ||
          (filter === "not_set_up" && notSetUp(row))) &&
        `${row.clan.name} ${row.clan.tag} ${row.clan.type} ${channels.get(row.settings.channel_id) || ""}`
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
