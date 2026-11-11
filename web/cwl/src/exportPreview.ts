import { compactRosterWeight } from "./rosterCompactWeight";
import { announcementMonthLabel } from "./announcementMonth";

export type ExportRow = Record<string, unknown>;

export const exportDateText = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "Never";

export function bonusSelectionStatus(row: ExportRow): string {
  return row.voided_at ? "Voided selection" : "Saved selection";
}

export function bonusSelectionReason(row: ExportRow): string {
  const value = row.voided_at ? row.void_reason : row.reason;
  return value === null || value === undefined || value === ""
    ? "—"
    : String(value);
}

export function matchesExportSearch(
  row: ExportRow,
  query: string,
  kind?: string,
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    row.player_name,
    row.tag,
    row.assigned_clan_name,
    row.assigned_clan_tag,
    row.clan_name,
    row.clan_tag,
    row.reason,
    row.void_reason,
    row.notes,
    row.cycle,
    kind === "bonus-history" ? bonusSelectionStatus(row) : null,
  ].some((value) =>
    String(value ?? "")
      .toLocaleLowerCase()
      .includes(needle),
  );
}

export function rosterResultSummary(row: ExportRow, prefix = ""): string {
  const match = row[`${prefix}matches_roster`];
  if (match === false) {
    const host =
      row[`${prefix}recorded_clan_name`] || row[`${prefix}recorded_clan_tag`];
    return host
      ? `Recorded for another assignment: ${host}`
      : "Recorded for another assignment";
  }
  const attacks = row[`${prefix}attacks`];
  const stars = row[`${prefix}stars`];
  if (attacks === null || attacks === undefined) {
    if (stars === null || stars === undefined) return "Not recorded";
  }
  return `${attacks ?? "—"} attacks · ${stars ?? "—"} stars`;
}

/** Presentation only: export requests and CSV values retain their full values. */
export function exportMonthLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value)
    ? announcementMonthLabel(value)
    : value;
}

export function exportWeightLabel(value: unknown): string {
  return compactRosterWeight(typeof value === "number" ? value : null);
}
