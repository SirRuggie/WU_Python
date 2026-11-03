type Entry = Record<string, unknown>;

const statusNames: Record<string, string> = {
  sent: "Sent",
  failed: "Failed",
  uncertain: "Check Discord",
  deleted_confirmed: "Post deleted",
  post_updated: "Post updated",
  pending: "Queued",
  sending: "Sending…",
  stale: "Settings changed",
  expired: "Expired",
  ledger_pending: "Delivery check pending",
};
const actionNames: Record<string, string> = {
  paused: "Paused",
  resumed: "Resumed",
  applied: "Settings saved",
  activated: "Automation on",
  skipped: "Reminder skipped",
  retry_requested: "Retry requested",
  restored: "Settings restored",
};
const ownLabel = (names: Record<string, string>, key: unknown) =>
  typeof key === "string" && Object.prototype.hasOwnProperty.call(names, key)
    ? names[key]
    : undefined;

export function reminderHistoryTitle(entry: Entry) {
  const keys = [entry.message_key, entry.message_id_key, entry.message_id];
  if (typeof entry.occurrence_id === "string")
    keys.push(entry.occurrence_id.split("|")[1]);
  for (const key of keys) {
    if (key === "signup") return "Signup message";
    if (key === "roster") return "Roster post";
    if (typeof key === "string" && /^reminder:(?:[1-9]|10)$/.test(key))
      return `Reminder ${key.split(":")[1]}`;
  }
  return ownLabel(actionNames, entry.action) || "Reminder activity";
}

export function reminderHistoryStatus(entry: Entry) {
  const status = String(entry.status || "");
  let label =
    ownLabel(statusNames, status) ||
    ownLabel(actionNames, entry.action) ||
    "Status unavailable";
  if (status === "sent" && entry.late === true) label = "Sent late";
  if (status === "skipped") {
    const reason = typeof entry.reason === "string" ? entry.reason.trim() : "";
    label = reason
      ? /^skipped(?:\s|:|$)/i.test(reason)
        ? reason
        : `Skipped: ${reason}`
      : "Skipped";
  }
  const audience = entry.variant || entry.pool;
  const name =
    audience === "main"
      ? "Main"
      : audience === "lazy"
        ? "Lazy"
        : audience
          ? "Audience unavailable"
          : "";
  return name ? `${name} · ${label}` : label;
}

export function reminderHistoryDetail(entry: Entry) {
  if (
    entry.status === "sent" &&
    entry.late === true &&
    typeof entry.original_due_at === "string" &&
    Number.isFinite(Date.parse(entry.original_due_at))
  )
    return { scheduled: entry.original_due_at };
  if (entry.status === "skipped") return null;
  const reason = entry.reason || entry.error;
  return typeof reason === "string" && reason ? { reason } : null;
}
