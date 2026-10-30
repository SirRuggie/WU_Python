export default function ReplacementDeparture({
  clan,
  seenAt,
}: {
  clan: string;
  seenAt?: string | null;
}) {
  const date = seenAt ? new Date(seenAt) : null;
  const validDate = date && Number.isFinite(date.getTime());
  return (
    <div className="replacement-departure">
      <span>Left clan · 48-hour grace period</span>
      <small>
        Last seen in {clan} ·{" "}
        {validDate ? (
          <time dateTime={date.toISOString()}>{date.toLocaleString()}</time>
        ) : (
          "Time unavailable"
        )}
      </small>
    </div>
  );
}
