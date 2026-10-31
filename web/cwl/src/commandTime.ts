export function relativeTime(
  at: string | null | undefined,
  now = Date.now(),
): string {
  if (!at || !Number.isFinite(Date.parse(at))) return "never";
  const seconds = Math.max(0, Math.floor((now - Date.parse(at)) / 1000));
  if (seconds < 60) return "just now";
  for (const [unit, size] of [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ] as const) {
    if (seconds >= size)
      return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
        -Math.floor(seconds / size),
        unit,
      );
  }
  return "just now";
}
