import { describe, expect, it } from 'vitest'
import { canUseSyncedResults, parseOptionalCount, participationValidation, validCwlCycle, visibleParticipation, syncStatusLabel, type ParticipationAccount } from './participation'

const row = (tag: string, name: string, pool: 'main' | 'lazy', attacks: number | null, stars: number | null, town_hall: number | null, clan: string | null): ParticipationAccount => ({
  tag, player_name: name, town_hall, pool, assigned_clan_tag: clan, assigned_clan_name: clan, attacks, stars, notes: '', revision: 0, updated_by: null, updated_at: null, in_latest_publication: true,
})
const rows = [row('#A', 'Alpha', 'main', null, 0, 15, '#ONE'), row('#B', 'Bravo', 'lazy', 2, 5, null, '#TWO'), row('#C', 'Charlie', 'main', 0, null, 13, '#ONE')]

describe('manual participation records', () => {
  it('keeps unrecorded values distinct from recorded zero', () => {
    expect(parseOptionalCount('')).toBeNull()
    expect(parseOptionalCount('0')).toBe(0)
    expect(parseOptionalCount('1.5')).toBeUndefined()
    expect(participationValidation(0, 0, '')).toBeNull()
    expect(participationValidation(0, 1, '')).toMatch(/three times/)
    expect(participationValidation(7, 21, '')).toBeNull()
    expect(participationValidation(8, null, '')).toMatch(/Attacks/)
  })
  it('allows explicit reset only when a synced value is known, including partial data', () => {
    const base = rows[0]
    expect(canUseSyncedResults({ ...base, attacks_override: true, source_attacks: null, source_stars: null })).toBe(false)
    expect(canUseSyncedResults({ ...base, attacks_override: true, source_attacks: 0, source_stars: null, source_complete: false })).toBe(true)
    expect(canUseSyncedResults({ ...base, attacks_override: false, stars_override: false, source_attacks: 2 })).toBe(false)
    expect(validCwlCycle('2026-10')).toBe(true)
    expect(validCwlCycle('2026-13')).toBe(false)
    expect(validCwlCycle('1999-10')).toBe(false)
    expect(syncStatusLabel('season_mismatch')).toBe('CWL month mismatch')
    expect(syncStatusLabel('no_data')).toBe('No CWL data')
  })
  it('filters both pools and clans and sorts missing numeric values last in either direction', () => {
    expect(visibleParticipation(rows, { search: '', pool: 'all', clan: 'all', sort: 'attacks-asc' }).map(x => x.tag)).toEqual(['#C', '#B', '#A'])
    expect(visibleParticipation(rows, { search: '', pool: 'all', clan: 'all', sort: 'attacks-desc' }).map(x => x.tag)).toEqual(['#B', '#C', '#A'])
    expect(visibleParticipation(rows, { search: '', pool: 'all', clan: 'all', sort: 'th-desc' }).map(x => x.tag)).toEqual(['#A', '#C', '#B'])
    expect(visibleParticipation(rows, { search: 'alp', pool: 'main', clan: '#ONE', sort: 'name' }).map(x => x.tag)).toEqual(['#A'])
  })
})
