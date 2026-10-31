/** Relative time with an explicit, keyboard-accessible exact-time disclosure. */
export default function HistoryTime({ at }: { at: string | null }) {
  if (!at || !Number.isFinite(Date.parse(at)))
    return <span>Date unavailable</span>;
  const date = new Date(at);
  const seconds = (date.getTime() - Date.now()) / 1000;
  const [unit, divisor]: [Intl.RelativeTimeFormatUnit, number] =
    Math.abs(seconds) < 60
      ? ["second", 1]
      : Math.abs(seconds) < 3600
        ? ["minute", 60]
        : Math.abs(seconds) < 86400
          ? ["hour", 3600]
          : ["day", 86400];
  const relative = new Intl.RelativeTimeFormat(undefined, {
    numeric: "auto",
  }).format(Math.round(seconds / divisor), unit);
  return (
    <details className="history-time">
      <summary aria-label={`${relative}; show exact time`}>{relative}</summary>
      <time dateTime={at}>{date.toLocaleString()}</time>
    </details>
  );
}
