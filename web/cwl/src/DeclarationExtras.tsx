import { comparisonAge } from "./comparisonLocation";
import type { DeclarationExtraClan } from "./declarationExtras";
import "./DeclarationExtras.css";

export default function DeclarationExtras({
  row,
  loading,
  error,
  now,
}: {
  row?: DeclarationExtraClan;
  loading: boolean;
  error: string;
  now: number;
}) {
  if (loading || (!row && !error))
    return (
      <p className="declaration-extras-status" role="status">
        Checking clan members…
      </p>
    );
  if (
    error ||
    row?.status !== "current" ||
    typeof row.count !== "number" ||
    !Array.isArray(row.extras) ||
    row.count !== row.extras.length
  )
    return (
      <p className="declaration-extras-status" role="status">
        Couldn't check
        {row?.checked_at
          ? ` · Last checked ${comparisonAge(row.checked_at, now)}`
          : ""}
      </p>
    );
  if (!row.count)
    return (
      <p className="declaration-extras-status">
        0 not on roster · Checked{" "}
        {comparisonAge(row.checked_at || undefined, now)}
      </p>
    );
  return (
    <details className="declaration-extras">
      <summary>⚠ {row.count} not on roster</summary>
      <p>
        Checked {comparisonAge(row.checked_at || undefined, now)} · Read-only
        flag
      </p>
      <ul>
        {row.extras?.map((member) => (
          <li key={member.tag}>
            <strong>{member.name}</strong> ·{" "}
            {member.town_hall ? `TH ${member.town_hall}` : "TH unavailable"} ·{" "}
            <code>{member.tag}</code>
            <span>{member.context}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
