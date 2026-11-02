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
  const unpublished = row?.unpublished || [];
  const unpublishedCount = row?.unpublished_count ?? unpublished.length;
  if (
    error ||
    row?.status !== "current" ||
    typeof row.count !== "number" ||
    !Array.isArray(row.extras) ||
    row.count !== row.extras.length ||
    !Array.isArray(unpublished) ||
    row.unpublished_count === null ||
    unpublishedCount !== unpublished.length ||
    unpublished.some((member) => member.not_published_yet !== true)
  ) {
    return (
      <p className="declaration-extras-status" role="status">
        Couldn't check
        {row?.checked_at
          ? ` · Last checked ${comparisonAge(row.checked_at, now)}`
          : " · Never checked"}
      </p>
    );
  }
  const low = row.low_th || [];
  const otherFillers =
    row.fillers?.filter(
      (member) =>
        !(
          typeof member.town_hall === "number" &&
          member.town_hall > 0 &&
          member.town_hall <= 9
        ),
    ) || [];
  const rows = [
    ...new Map(
      [...low, ...otherFillers, ...row.extras, ...unpublished].map((member) => [
        member.tag,
        member,
      ]),
    ).values(),
  ];
  const counts = [
    `${row.count} not on roster`,
    ...(unpublishedCount ? [`${unpublishedCount} not published yet`] : []),
    ...(low.length ? [`${low.length} low TH in clan`] : []),
    ...(otherFillers.length
      ? [
          `${otherFillers.length} other filler${otherFillers.length === 1 ? "" : "s"} in clan`,
        ]
      : []),
  ].join(" · ");
  if (!rows.length)
    return (
      <p className="declaration-extras-status">
        0 not on roster · Checked{" "}
        {comparisonAge(row.checked_at || undefined, now)}
      </p>
    );
  return (
    <details className={`declaration-extras${row.count ? "" : " is-neutral"}`}>
      <summary>
        {row.count ? "⚠ " : ""}
        {counts}
      </summary>
      <p>Checked {comparisonAge(row.checked_at || undefined, now)}</p>
      <DeclarationMemberMarks rows={rows} control={markControl} />
    </details>
  );
}
