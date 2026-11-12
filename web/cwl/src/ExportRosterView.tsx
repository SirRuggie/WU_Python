import AccountCard from "./AccountCard";
import ExportRecordCard from "./ExportRecordCard";
import { exportGroups, groupLabel, type ExportKind } from "./exportHistory";
import { exportWeightLabel, type ExportRow } from "./exportPreview";
export default function ExportRosterView({
  rows,
  kind,
}: {
  rows: ExportRow[];
  kind: Exclude<ExportKind, "bonus-history">;
}) {
  return (
    <div className="export-clans">
      {exportGroups(rows).map((group) => (
        <section className="export-clan" key={group.key}>
          <h2>{groupLabel(group)}</h2>
          <ul className="export-records">
            {group.rows.map((row, index) => (
              <li key={`${String(row.tag)}:${index}`}>
                {kind === "accounts" ? (
                  <AccountCard
                    className="export-record account-card-plain"
                    thLevel={
                      typeof row.town_hall === "number" ? row.town_hall : null
                    }
                    name={String(row.player_name || "—")}
                    meta={[
                      row.town_hall != null ? `TH ${row.town_hall}` : null,
                      String(row.tag ?? ""),
                    ]}
                    values={
                      <strong className="export-weight">
                        {exportWeightLabel(row.effective_weight)}
                      </strong>
                    }
                  />
                ) : (
                  <ExportRecordCard kind={kind} row={row} />
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
