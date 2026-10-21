import type { Pool } from './api'

export type ParticipationAccount = {
  roster_token?: string
  previous_results?: { pool: string; assigned_clan_name: string | null; assigned_clan_tag: string | null; attacks: number | null; stars: number | null }
  tag: string
  player_name: string
  town_hall: number | null
  pool: Pool
  assigned_clan_tag: string | null
  assigned_clan_name: string | null
  attacks: number | null
  stars: number | null
  notes: string
  revision: number
  updated_by: string | null
  updated_at: string | null
  in_latest_publication: boolean
  recorded_publication_version?: number | null
  roster_changed?: boolean
  source_attacks?: number | null
  source_stars?: number | null
  source_status?: string
  source_checked_at?: string | null
  source_complete?: boolean
  attacks_override?: boolean
  stars_override?: boolean
  source_warning?: string | null
  attacks_origin?: 'source' | 'manual' | 'unknown'
  stars_origin?: 'source' | 'manual' | 'unknown'
}
export type ParticipationSync = { cycle: string | null; cycle_source: 'settings' | 'manage_binding' | 'none'; enabled: boolean; status: string; last_checked_at: string | null; last_success_at: string | null; warning: string | null }
export type ParticipationData = { historical_accounts_count?: number; roster_source?: string; publication_version: number | null; accounts: ParticipationAccount[]; sync?: ParticipationSync }
export type ParticipationSort = 'name' | 'attacks-asc' | 'attacks-desc' | 'stars-asc' | 'stars-desc' | 'th-asc' | 'th-desc'
export type ParticipationFilters = { search: string; pool: Pool | 'all'; clan: string; sort: ParticipationSort }

export function participationValidation(attacks: number | null, stars: number | null, notes: string): string | null {
  if (attacks !== null && (!Number.isInteger(attacks) || attacks < 0 || attacks > 7)) return 'Attacks must be a whole number from 0 to 7.'
  if (stars !== null && (!Number.isInteger(stars) || stars < 0 || stars > 21)) return 'Stars must be a whole number from 0 to 21.'
  if (attacks !== null && stars !== null && stars > attacks * 3) return 'Stars cannot exceed three times the recorded attacks.'
  if (notes.length > 2000) return 'Notes must be 2,000 characters or fewer.'
  return null
}
export function parseOptionalCount(raw: string): number | null | undefined {
  if (!raw.trim()) return null
  if (!/^\d+$/.test(raw.trim())) return undefined
  return Number(raw.trim())
}
export function visibleParticipation(accounts: ParticipationAccount[], filters: ParticipationFilters): ParticipationAccount[] {
  const query = filters.search.trim().toLocaleLowerCase()
  const filtered = accounts.filter(account =>
    (filters.pool === 'all' || account.pool === filters.pool) &&
    (filters.clan === 'all' || (account.assigned_clan_tag || '') === filters.clan) &&
    (!query || [account.player_name, account.tag, account.assigned_clan_name || '', account.assigned_clan_tag || ''].some(value => value.toLocaleLowerCase().includes(query)))
  )
  const field = filters.sort.startsWith('attacks') ? 'attacks' : filters.sort.startsWith('stars') ? 'stars' : filters.sort.startsWith('th') ? 'town_hall' : null
  const direction = filters.sort.endsWith('desc') ? -1 : 1
  return filtered.sort((left, right) => {
    if (field) {
      const a = left[field], b = right[field]
      if (a === null && b !== null) return 1
      if (b === null && a !== null) return -1
      if (a !== null && b !== null && a !== b) return (a - b) * direction
    }
    return left.player_name.localeCompare(right.player_name) || left.tag.localeCompare(right.tag)
  })
}

export function canUseSyncedResults(account: ParticipationAccount): boolean {
  return !!(account.attacks_override || account.stars_override || account.roster_changed) && (account.source_attacks !== null && account.source_attacks !== undefined || account.source_stars !== null && account.source_stars !== undefined)
}
export function validCwlCycle(value: string): boolean { return /^20\d{2}-(0[1-9]|1[0-2])$/.test(value) }

export function syncStatusLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = { never: 'Not checked', complete: 'Complete', partial: 'Partial', preparation: 'War preparation', stale: 'Stale', unavailable: 'Unavailable', unassigned: 'No assigned clans', season_mismatch: 'CWL month mismatch', no_data: 'No CWL data', missing: 'Not checked', historical: 'Historical' }
  return labels[value || ''] || value || 'Not configured'
}
