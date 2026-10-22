import { describe, expect, it } from 'vitest'
import { assignmentOptions, filterRosterAccounts, parseWeightK, sortRosterAccounts, weightInputText, weightText, type RosterAccount, type RosterClan } from './roster'
const clans: RosterClan[] = [
  { tag: '#MAIN', name: 'Main host', archived: false, pool: 'main', capacity: 15, effective_capacity: 15, min_weight: null, max_weight: null, lower_league: null, assigned_count: 0 },
  { tag: '#LAZY', name: 'Lazy host', archived: false, pool: 'lazy', capacity: 30, effective_capacity: 30, min_weight: null, max_weight: null, lower_league: null, assigned_count: 0 },
  { tag: '#OLD', name: 'Old host', archived: true, pool: null, capacity: null, effective_capacity: 50, min_weight: null, max_weight: null, lower_league: null, assigned_count: 1 },
]
const accounts: RosterAccount[] = [
  { tag: '#ONE', user_id: '111', pool: 'main', player_name: 'Alpha', town_hall: 16, prefer_crystal_1_or_lower: false, source_weight: 175000, source_status: 'current', source_name: 'Fixture', source_checked_at: null, source_modified_at: null, manual_weight: null, effective_weight: 175000, assigned_clan_tag: null, kept: false },
  { tag: '#TWO', user_id: '222', pool: 'lazy', player_name: 'Beta', town_hall: 15, prefer_crystal_1_or_lower: true, source_weight: null, source_status: 'missing', source_name: null, source_checked_at: null, source_modified_at: null, manual_weight: null, effective_weight: null, assigned_clan_tag: '#MAIN', kept: true },
  { tag: '#THREE', user_id: '333', pool: 'main', player_name: 'Gamma', town_hall: null, prefer_crystal_1_or_lower: false, source_weight: 150000, source_status: 'current', source_name: 'Fixture', source_checked_at: null, source_modified_at: null, manual_weight: null, effective_weight: 150000, assigned_clan_tag: '#OLD', kept: true },
]
describe('staff roster controls', () => {
  it('offers active hosts regardless of signup pool while preserving archived assignments in snapshot', () => { expect(assignmentOptions(clans).map(clan => clan.tag)).toEqual(['#MAIN', '#LAZY']); expect(clans.find(clan => clan.tag === '#OLD')?.archived).toBe(true) })
  it('filters by identity, pool and assignment', () => { expect(filterRosterAccounts(accounts, '222', 'lazy', 'assigned').map(account => account.tag)).toEqual(['#TWO']); expect(filterRosterAccounts(accounts, 'Alpha', 'all', 'unassigned').map(account => account.tag)).toEqual(['#ONE']) })
  it('sorts numeric town hall and effective weight with missing values last in both directions', () => { expect(sortRosterAccounts(accounts, 'town_hall_asc').map(account => account.tag)).toEqual(['#TWO', '#ONE', '#THREE']); expect(sortRosterAccounts(accounts, 'town_hall_desc').map(account => account.tag)).toEqual(['#ONE', '#TWO', '#THREE']); expect(sortRosterAccounts(accounts, 'weight_asc').map(account => account.tag)).toEqual(['#THREE', '#ONE', '#TWO']); expect(sortRosterAccounts(accounts, 'weight_desc').map(account => account.tag)).toEqual(['#ONE', '#THREE', '#TWO']) })
  it('keeps missing weights visible and parses nullable rule boundaries', () => { expect(weightText(null)).toBe('Missing weight'); expect(weightText(174500)).toBe('174.5k'); expect(weightInputText(174500)).toBe('174.5'); expect(parseWeightK('')).toBeNull(); expect(parseWeightK('174')).toBe(174000); expect(parseWeightK('174.5')).toBe(174500); expect(() => parseWeightK('-1')).toThrow() })
})
