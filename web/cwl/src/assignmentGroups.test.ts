import { describe, expect, it } from 'vitest'
import { groupAssignments } from './assignmentGroups'
import type { MemberAssignment } from './publication'
const row = (tag: string, name: string, clanTag: string | null, clanName: string | null, pool: 'main' | 'lazy'): MemberAssignment => ({ tag, player_name: name, town_hall: 15, pool, assigned_clan_tag: clanTag, assigned_clan_name: clanName })

describe('member assignment grouping', () => {
  it('combines both pools in one hosting clan and puts awaiting placement last', () => {
    const input = [row('#C', 'Charlie', null, null, 'lazy'), row('#B', 'Bravo', '#TWO', 'Zeta', 'main'), row('#D', 'Delta', '#ONE', 'Alpha', 'lazy'), row('#A', 'Alpha', '#ONE', 'Alpha', 'main')]
    const groups = groupAssignments(input)
    expect(groups.map(group => group.clanTag)).toEqual(['#ONE', '#TWO', null])
    expect(groups[0].accounts.map(account => account.tag)).toEqual(['#A', '#D'])
    expect(groups[0].accounts.map(account => account.pool)).toEqual(['main', 'lazy'])
    expect(groups[2].accounts.map(account => account.tag)).toEqual(['#C'])
    expect(input[0].tag).toBe('#C')
  })
  it('falls back to a clan tag when its name is unavailable', () => {
    expect(groupAssignments([row('#A', 'Alpha', '#HOST', null, 'main')])[0].clanName).toBe('#HOST')
    expect(groupAssignments([row('#A', 'Alpha', '#HOST', null, 'main'), row('#B', 'Bravo', '#HOST', 'Warriors', 'lazy')])[0].clanName).toBe('Warriors')
  })
})
