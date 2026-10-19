import { describe, expect, it } from 'vitest'
import { readinessAccounts } from './readiness'
import type { RosterAccount, RosterClan } from './roster'
const accounts = [
  { tag: '#A', assigned_clan_tag: '#CLAN', effective_weight: 100 },
  { tag: '#B', assigned_clan_tag: '#CLAN', effective_weight: null },
  { tag: '#C', assigned_clan_tag: null, effective_weight: 0 },
] as RosterAccount[]
const clans = [{ tag: '#CLAN', effective_capacity: 1, assigned_count: 0 }] as RosterClan[]
describe('roster readiness', () => {
  it('uses effective weight and keeps zero distinct from missing', () => {
    expect(readinessAccounts(accounts, clans, 'missing_weight').map(a => a.tag)).toEqual(['#B'])
    expect(readinessAccounts(accounts, clans, 'unassigned').map(a => a.tag)).toEqual(['#C'])
  })
  it('counts current placements across both pools instead of trusting cached counts', () => {
    expect(readinessAccounts(accounts, clans, 'over_capacity').map(a => a.tag)).toEqual(['#A', '#B'])
    expect(readinessAccounts(accounts, [{ ...clans[0], effective_capacity: 2 }], 'over_capacity')).toEqual([])
    expect(readinessAccounts(accounts.slice(1), clans, 'over_capacity')).toEqual([])
  })
})
