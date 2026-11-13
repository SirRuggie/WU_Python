/** Numbers always group with en-US so weights read the same for every viewer. */
export const NUMBER_LOCALE = "en-US";

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  return value.toLocaleString(NUMBER_LOCALE, options);
}

type DateInput = Date | string | number | null | undefined;

/** Locale and zone default to the viewer's; tests pin both. */
type DateOptions = { locale?: string; timeZone?: string };

/** Shown when a date is missing or cannot be read. Helpers never throw. */
export const DATE_FALLBACK = "—";

function readDate(value: DateInput): Date | null {
  if (value === null || value === undefined) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatWith(
  value: DateInput,
  style: Intl.DateTimeFormatOptions,
  { locale, timeZone }: DateOptions,
): string {
  const date = readDate(value);
  if (!date) return DATE_FALLBACK;
  return new Intl.DateTimeFormat(locale, { ...style, timeZone }).format(date);
}

/** Dates and times follow the viewer's locale with fixed, explicit options. */
export function formatDateTime(
  value: DateInput,
  options: DateOptions & { seconds?: boolean } = {},
): string {
  return formatWith(
    value,
    { dateStyle: "medium", timeStyle: options.seconds ? "medium" : "short" },
    options,
  );
}

export function formatDate(value: DateInput, options: DateOptions = {}) {
  return formatWith(value, { dateStyle: "medium" }, options);
}

export function formatTime(value: DateInput, options: DateOptions = {}) {
  return formatWith(value, { timeStyle: "short" }, options);
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
