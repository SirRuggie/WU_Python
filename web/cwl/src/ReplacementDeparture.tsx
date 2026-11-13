import { formatDateTime } from "./format";
import { comparisonAge } from "./comparisonLocation";

export default function ReplacementDeparture({
  clan,
  seenAt,
  currentClan,
}: {
  clan: string;
  seenAt?: string | null;
  currentClan?: string | null;
}) {
  const date = seenAt ? new Date(seenAt) : null;
  const validDate = date && Number.isFinite(date.getTime());
  return (
    <div className="replacement-departure">
      <span>
        Left {clan}
        {currentClan ? ` · now in ${currentClan}` : ""}
      </span>
      {validDate ? (
        <details>
          <summary title={formatDateTime(date)}>
            <time dateTime={date.toISOString()}>
              {comparisonAge(seenAt!, Date.now())}
            </time>
          </summary>
          <small>{formatDateTime(date)}</small>
        </details>
      ) : (
        <small>Time unavailable</small>
      )}
    </div>
  );
}
