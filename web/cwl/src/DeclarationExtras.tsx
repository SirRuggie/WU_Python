import DeclarationMemberMarks, {
  type DeclarationMarkControl,
} from "./DeclarationMemberMarks";
import { comparisonAge } from "./comparisonLocation";
import type { DeclarationExtraClan } from "./declarationExtras";
import "./DeclarationExtras.css";

export default function DeclarationExtras({
  row,
  markControl,
  loading,
  error,
  now,
}: {
  row?: DeclarationExtraClan;
  markControl?: DeclarationMarkControl;
  loading: boolean;
  error: string;
  now: number;
}) {
  if (loading)
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
          : " · Never checked"}
      </p>
    );
  return (
    <>
      {!!row.low_th?.length && (
        <details className="declaration-low-th">
          <summary>{row.low_th.length} low TH in clan</summary>
          <DeclarationMemberMarks rows={row.low_th} control={markControl} />
        </details>
      )}
      {!!row.fillers?.length && (
        <details className="declaration-fillers">
          <summary>
            {row.fillers.length} filler{row.fillers.length === 1 ? "" : "s"} in
            clan
          </summary>
          <DeclarationMemberMarks rows={row.fillers} control={markControl} />
        </details>
      )}
      {!row.count ? (
        <p className="declaration-extras-status">
          0 not on roster · Checked{" "}
          {comparisonAge(row.checked_at || undefined, now)}
        </p>
      ) : (
        <details className="declaration-extras">
          <summary>⚠ {row.count} not on roster</summary>
          <p>Checked {comparisonAge(row.checked_at || undefined, now)}</p>
          <DeclarationMemberMarks rows={row.extras} control={markControl} />
        </details>
      )}
    </>
  );
}
