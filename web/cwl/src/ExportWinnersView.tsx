import AccountCard from "./AccountCard";
import CardTally from "./CardTally";
import { Chip } from "./rosterUi/primitives";
import { exportGroups, groupLabel } from "./exportHistory";
import type { ExportRow } from "./exportPreview";
export default function ExportWinnersView({ rows }: { rows: ExportRow[] }) {
  return (
    <div className="export-clans">
      {exportGroups(
        rows.filter((row) => !row.voided_at),
        true,
      ).map((group) => (
        <section className="export-clan" key={group.key}>
          <h2>{groupLabel(group)}</h2>
          <ul className="export-records">
            {group.rows.map((row, index) => (
              <li key={`${String(row.tag)}:${index}`}>
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
                    row.attacks != null || row.stars != null ? (
                      <CardTally
                        attacks={String(row.attacks ?? "—")}
                        stars={String(row.stars ?? "—")}
                      />
                    ) : undefined
                  }
                  flags={
                    row.source === "import"
                      ? [<Chip key="import">Imported</Chip>]
                      : []
                  }
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
