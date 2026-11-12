import AccountCard from "./AccountCard";
import CardTally from "./CardTally";
import {
  syncStatusLabel,
  type ParticipationDisplayStatus,
} from "./participation";
import {
  exportDateText,
  rosterResultSummary,
  type ExportRow,
} from "./exportPreview";

/** Read-only saved result or signup, inside its hosting-clan group. */
export default function ExportRecordCard({
  kind,
  row,
}: {
  kind: "participation" | "participation-history";
  row: ExportRow;
}) {
  const recorded = kind === "participation-history";
  const tally =
    recorded ||
    (row.matches_roster !== false &&
      (row.attacks != null || row.stars != null));
  const capture =
    (row.display_status as ParticipationDisplayStatus | undefined)?.label ||
    syncStatusLabel(row.source_status as string | null | undefined);
  return (
    <AccountCard
      className="export-record account-card-plain"
      thLevel={typeof row.town_hall === "number" ? row.town_hall : null}
      name={String(row.player_name || "—")}
      meta={[
        row.town_hall != null ? `TH ${row.town_hall}` : null,
        String(row.tag ?? ""),
      ]}
      values={
        tally ? (
          <CardTally
            attacks={String(row.attacks ?? "—")}
            stars={String(row.stars ?? "—")}
          />
        ) : undefined
      }
      flags={[
        !tally ? rosterResultSummary(row) : null,
        `Clash capture: ${capture}`,
      ]}
    >
      {recorded && (Boolean(row.notes) || Boolean(row.updated_at)) && (
        <details className="export-record-details">
          <summary>Saved details</summary>
          {Boolean(row.updated_at) && (
            <p>Last saved {exportDateText(String(row.updated_at))}</p>
          )}
          {Boolean(row.notes) && <p>{String(row.notes)}</p>}
        </details>
      )}
    </AccountCard>
  );
}
