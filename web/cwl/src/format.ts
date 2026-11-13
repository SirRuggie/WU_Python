/** Numbers always group with en-US so weights read the same for every viewer. */
export const NUMBER_LOCALE = "en-US";

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  return value.toLocaleString(NUMBER_LOCALE, options);
}

type DateInput = Date | string | number;

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

/** Dates and times follow the viewer's locale with fixed, explicit options. */
export function formatDateTime(value: DateInput): string {
  return dateTimeFormat.format(new Date(value));
}

export function formatDate(value: DateInput): string {
  return dateFormat.format(new Date(value));
}

export function formatTime(value: DateInput): string {
  return timeFormat.format(new Date(value));
}

/** Month label for a `YYYY-MM` cycle, always read in UTC. */
export function formatCycleMonth(
  cycle: string,
  month: "long" | "short" = "long",
): string {
  return new Intl.DateTimeFormat(undefined, {
    month,
    ...(month === "short" ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).format(new Date(`${cycle}-01T00:00:00Z`));
}
