import { formatDateTime } from "./format";
import { compactRosterWeight } from "./rosterCompactWeight";
import { announcementMonthLabel } from "./announcementMonth";

export type ExportRow = Record<string, unknown>;

export const exportDateText = (value: string | null) =>
  value ? formatDateTime(new Date(value)) : "Never";

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

/** Presentation only: export requests and workbook values retain their full values. */
export function exportMonthLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value)
    ? announcementMonthLabel(value)
    : value;
}

export function exportWeightLabel(value: unknown): string {
  return compactRosterWeight(typeof value === "number" ? value : null);
}
