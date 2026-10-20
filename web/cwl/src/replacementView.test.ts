import { expect, it } from 'vitest'
import { groupReplacements } from './replacementView'

it('groups accounts by clan without changing backend priority and weight order', () => {
  const rows = [
    { clan_tag: '#A', clan_name: 'Alpha', player_tag: '#HIGH' },
    { clan_tag: '#B', clan_name: 'Beta', player_tag: '#BETA' },
    { clan_tag: '#A', clan_name: 'Alpha', player_tag: '#UNKNOWN_WEIGHT' },
  ]
  expect(groupReplacements(rows).map(group => [group.name, group.accounts.map(item => item.player_tag)])).toEqual([
    ['Alpha', ['#HIGH', '#UNKNOWN_WEIGHT']],
    ['Beta', ['#BETA']],
  ])
})

import { selectableTags, toggleRosterTag } from './replacementView'
it('selects eligible roster accounts without changing listed entries', () => {
  const roster = [
    { player_tag: '#ONE', player_name: 'One', is_manual: false },
    { player_tag: '#TWO', player_name: 'Two', is_manual: true },
    { player_tag: '#THREE', player_name: 'Three', is_manual: false },
  ]
  expect(selectableTags(roster)).toEqual(['#ONE', '#THREE'])
  expect(toggleRosterTag([], '#ONE', roster)).toEqual(['#ONE'])
  expect(toggleRosterTag(['#ONE'], '#ONE', roster)).toEqual([])
  expect(toggleRosterTag(['#ONE'], '#TWO', roster)).toEqual(['#ONE'])
})

import { bulkSaveMessage } from './replacementView'
it('reports actual saved and skipped counts', () => {
  expect(bulkSaveMessage({ added_count: 1, skipped_count: 2 })).toBe('1 account added. 2 already listed.')
  expect(bulkSaveMessage({ added_count: 0, skipped_count: 3 })).toBe('0 accounts added. 3 already listed.')
})
