import type { Pool } from "../api";
import type { Campaign } from "../reminderCampaign";

export type ReminderErrorCode =
  | "no_channel"
  | "unknown_channel"
  | "unknown_role"
  | "empty_title"
  | "empty_body";

export type ReminderError = { code: ReminderErrorCode; label: string };
export type ReminderLookup<T extends { id: string }> = {
  items: T[];
  loading: boolean;
  error: string;
};
export type ReminderLookups = {
  channels: ReminderLookup<{ id: string }>;
  roles: ReminderLookup<{ id: string }>;
};

const labels: Record<ReminderErrorCode, string> = {
  no_channel: "No channel",
  unknown_channel: "Unknown channel",
  unknown_role: "Unknown role",
  empty_title: "No title",
  empty_body: "No message",
};

/** Draft-only display errors; they never change Save eligibility or requests. */
export function variantErrors(
  campaign: Campaign,
  messageId: string,
  pool: Pool,
  lookups: ReminderLookups,
): ReminderError[] {
  const message = campaign.messages[messageId];
  const variant = message?.variants[pool];
  if (!message?.enabled || !variant || variant.enabled === false) return [];
  const errors: ReminderErrorCode[] = [];
  if (!variant.destination_channel_id.trim()) errors.push("no_channel");
  else if (
    !lookups.channels.loading &&
    !lookups.channels.error &&
    !lookups.channels.items.some(
      (channel) => channel.id === variant.destination_channel_id,
    )
  )
    errors.push("unknown_channel");
  if (
    !lookups.roles.loading &&
    !lookups.roles.error &&
    variant.role_ids.some(
      (id) => !lookups.roles.items.some((role) => role.id === id),
    )
  )
    errors.push("unknown_role");
  if (!variant.title.trim()) errors.push("empty_title");
  if (!variant.body.trim()) errors.push("empty_body");
  return errors.map((code) => ({ code, label: labels[code] }));
}
