export type ExportRow = Record<string, unknown>;

export function bonusSelectionStatus(row: ExportRow): string {
  return row.voided_at ? 'Voided selection' : 'Saved selection';
}

export function bonusSelectionReason(row: ExportRow): string {
  const value = row.voided_at ? row.void_reason : row.reason;
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

export function matchesExportSearch(row: ExportRow, query: string, kind?: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    row.player_name, row.tag, row.assigned_clan_name, row.assigned_clan_tag,
    row.clan_name, row.clan_tag, row.reason, row.void_reason,
    row.notes, row.cycle, kind === 'bonus-history' ? bonusSelectionStatus(row) : null,
  ].some(value => String(value ?? '').toLocaleLowerCase().includes(needle));
}

export function rosterResultSummary(row: ExportRow, prefix = ''): string {
  const match = row[`${prefix}matches_roster`];
  if (match === false) {
    const host = row[`${prefix}recorded_clan_name`] || row[`${prefix}recorded_clan_tag`];
    return host ? `Recorded for another assignment: ${host}` : 'Recorded for another assignment';
  }
  const attacks = row[`${prefix}attacks`];
  const stars = row[`${prefix}stars`];
  if (attacks === null || attacks === undefined) {
    if (stars === null || stars === undefined) return 'Not recorded';
  }
  return `${attacks ?? '—'} attacks · ${stars ?? '—'} stars`;
}
