import { expect, it } from 'vitest'
import type { Account } from './api'
import { searchIndex, matchingResults } from './dashboardSearch'
const accounts = [{tag:'#ABC',name:'<script>Player</script>',current_clan_tag:'#CLAN',current_clan_name:'Family',town_hall:18}] as Account[]
it('deduplicates linked clans against the authorized family directory', () => {
  const index = searchIndex(accounts, [{tag:'#CLAN',name:'Family'}])
  expect(index).toHaveLength(2)
  expect(index[1].detail).toBe('Family clan')
})
it('matches names and tags case-insensitively without requiring a hash', () => {
  const index = searchIndex(accounts, [])
  expect(matchingResults(index, ' abc ', 'all').map(item=>item.tag)).toEqual(['#ABC'])
  expect(matchingResults(index, '#clan', 'clan')).toHaveLength(1)
  expect(matchingResults(index, 'family', 'player')).toHaveLength(1)
  expect(matchingResults(index, 'missing', 'all')).toEqual([])
})
it('does not invent clans for players without a current clan', () => {
  expect(searchIndex([{...accounts[0],current_clan_tag:null}], [])).toHaveLength(1)
})
