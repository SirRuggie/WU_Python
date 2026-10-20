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
