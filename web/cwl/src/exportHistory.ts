import type { Season } from "./api";
import { exportMonthLabel } from "./exportPreview";
import type { ExportRow } from "./exportPreview";
export type ExportKind =
  "accounts" | "participation" | "participation-history" | "bonus-history";
const validMonth = (value: string | null | undefined) =>
  value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value) ? value : "";
const seasonCycle = (season: Season) =>
  validMonth(season.cwl_month) || validMonth(season.label);
export const seasonMonthLabel = (season: Season) =>
  exportMonthLabel(seasonCycle(season) || season.label);
export function monthSeasons(seasons: Season[]): Season[] {
  return [...seasons].sort(
    (a, b) => seasonCycle(b).localeCompare(seasonCycle(a)) || b.id - a.id,
  );
}
export function exportGroups(rows: ExportRow[], winners = false) {
  const groups = new Map<
    string,
    { key: string; name: string; pool: string; rows: ExportRow[] }
  >();
  for (const row of rows) {
    const pool = String(row.pool ?? "");
    const tag = String(row[winners ? "clan_tag" : "assigned_clan_tag"] ?? "");
    const name = String(
      row[winners ? "clan_name" : "assigned_clan_name"] || tag || "Unplaced",
    );
    const key = `${pool}:${tag || name}`;
    if (!groups.has(key)) groups.set(key, { key, name, pool, rows: [] });
    groups.get(key)!.rows.push(row);
  }
  const rank = (pool: string) =>
    pool === "main" ? 0 : pool === "lazy" ? 1 : 2;
  return [...groups.values()]
    .sort((a, b) => rank(a.pool) - rank(b.pool) || a.name.localeCompare(b.name))
    .map((group) => ({
      ...group,
      rows: [...group.rows].sort((a, b) =>
        String(a.player_name ?? "").localeCompare(String(b.player_name ?? "")),
      ),
    }));
}
export const groupLabel = (group: ReturnType<typeof exportGroups>[number]) =>
  `${group.name} · ${group.pool === "main" ? "Main CWL" : group.pool === "lazy" ? "Lazy CWL" : "Unassigned"} · ${group.rows.length} account${group.rows.length === 1 ? "" : "s"}`;
