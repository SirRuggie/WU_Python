import type { Pool } from './api'
export type RosterAccount = {
  current_clan_tag?: string | null; current_clan_name?: string | null; current_clan_status?: 'current' | 'stale' | 'unavailable';
  auto_placement_reason?: string | null; auto_placement_note?: string | null;
  tag: string; user_id: string; pool: Pool; player_name: string; town_hall: number | null;
  prefer_crystal_1_or_lower: boolean; source_weight: number | null; source_status: 'missing' | 'current' | 'unavailable'; source_name: string | null; source_checked_at: string | null; source_modified_at: string | null;
  initial_manual_weight?: number | null; manual_weight: number | null; effective_weight: number | null; assigned_clan_tag: string | null; kept: boolean
}
export type RosterClan = { cwl_league?: string | null; cwl_league_stale?: boolean; tag: string; name: string; archived: boolean; pool: Pool | null; capacity: number | null; effective_capacity: number; min_weight: number | null; max_weight: number | null; lower_league: boolean | null; assigned_count: number }
export type RosterUndo = { id: number; label: string; revision: number }
export type RosterSnapshot = { revision: number; accounts: RosterAccount[]; clans: RosterClan[]; undo: RosterUndo | null }
export type AutoPreview = { revision: number; placements: { tag: string; assigned_clan_tag: string }[]; unassigned: { tag: string; reason: string }[] }
export type RosterSort = 'name' | 'town_hall_asc' | 'town_hall_desc' | 'weight_asc' | 'weight_desc'
export function assignmentOptions(clans: RosterClan[], pool?: Pool): RosterClan[] { return clans.filter(clan => !clan.archived && (pool !== 'lazy' || clan.pool === 'lazy')) }
export function filterRosterAccounts(accounts: RosterAccount[], search: string, pool: Pool | 'all', assignment: 'all' | 'assigned' | 'unassigned') {
  const term = search.trim().toLowerCase()
  return accounts.filter(account => (pool === 'all' || account.pool === pool)
    && (assignment === 'all' || (assignment === 'assigned' ? !!account.assigned_clan_tag : !account.assigned_clan_tag))
    && (!term || [account.player_name, account.tag, account.user_id].some(value => value.toLowerCase().includes(term))))
}
export function sortRosterAccounts(accounts: RosterAccount[], sort: RosterSort): RosterAccount[] {
  const tie = (a: RosterAccount, b: RosterAccount) => a.player_name.localeCompare(b.player_name) || a.tag.localeCompare(b.tag)
  const spec = sort === 'town_hall_asc' ? { key: 'town_hall' as const, direction: 1 } : sort === 'town_hall_desc' ? { key: 'town_hall' as const, direction: -1 } : sort === 'weight_asc' ? { key: 'effective_weight' as const, direction: 1 } : sort === 'weight_desc' ? { key: 'effective_weight' as const, direction: -1 } : null
  return [...accounts].sort((a, b) => {
    if (!spec) return tie(a, b)
    const left = a[spec.key], right = b[spec.key]
    if (left === null) return right === null ? tie(a, b) : 1
    if (right === null) return -1
    return (left - right) * spec.direction || tie(a, b)
  })
}
export function weightText(weight: number | null): string { return weight === null ? 'Missing weight' : `${(weight / 1000).toLocaleString(undefined, { maximumFractionDigits: 3 })}k` }
export function weightInputText(weight: number | null): string { return weight === null ? '' : String(weight / 1000) }
export function parseWeightK(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  const fullWeight = parsed * 1000
  if (!Number.isFinite(parsed) || parsed < 0 || !Number.isSafeInteger(fullWeight)) throw new Error('Enter a weight in thousands, such as 174 or 174.5, or leave the field blank.')
  return fullWeight
}
