import { formatDate, formatDateTime } from "../format";

export function targetCwlMonth(cycle: string | null) {
  if (!cycle || !/^\d{4}-\d{2}$/.test(cycle)) return "CWL month unavailable";
  const [year, month] = cycle.split("-").map(Number);
  if (month < 1 || month > 12) return "CWL month unavailable";
  return formatDate(new Date(Date.UTC(year, month, 1)), {
    timeZone: "UTC",
    format: { month: "long", year: "numeric" },
  });
}

export function shortReminderTime(value?: string | null, timeZone?: string) {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unavailable";
  try {
    return formatDateTime(date, {
      ...(timeZone ? { timeZone } : {}),
      format: {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      },
    });
  } catch {
    return "Time unavailable";
  }
}

export function reminderStatusLabel(status?: string) {
  switch (status) {
    case "scheduled":
    case "pending":
      return "Upcoming";
    case "sent":
      return "Sent";
    case "skipped":
      return "Skipped";
    case "paused":
      return "Paused";
    case "inactive":
      return "Not scheduled";
    default:
      return "Check History";
  }
}
