import { describe, expect, it } from 'vitest'
import { availableSelection, dashboardRows, filterDashboardRows } from './dashboard'
import type { Account, Signup } from './api'
const accounts = [
  { tag: '#A', name: 'Alpha', town_hall: 16, current_clan_name: 'Home' },
  { tag: '#B', name: 'Beta', town_hall: 18, current_clan_name: 'Home' },
  { tag: '#C', name: 'Charlie', town_hall: null, current_clan_name: null },
] as Account[]
const saved = [{ tag: '#B', pool: 'lazy' }, { tag: '#C', pool: 'main' }] as Signup[]
const rows = dashboardRows(accounts, saved, [{ tag: '#B', player_name: 'Beta', town_hall: 18, pool: 'lazy', assigned_clan_tag: '#Z', assigned_clan_name: 'Destination' }])
describe('dashboard account selection and next steps', () => {
  it('distinguishes unsigned, awaiting placement, and assigned accounts', () => {
    expect(filterDashboardRows(rows, 'unsigned', '', 'th').map(row => row.tag)).toEqual(['#A'])
    expect(filterDashboardRows(rows, 'waiting', '', 'th').map(row => row.tag)).toEqual(['#C'])
    expect(filterDashboardRows(rows, 'assigned', '', 'th').map(row => row.tag)).toEqual(['#B'])
  })
  it('sorts unknown Town Halls last and searches hosting clans and player tags', () => {
    expect(filterDashboardRows(rows, 'all', '', 'th').map(row => row.tag)).toEqual(['#B','#A','#C'])
    expect(filterDashboardRows(rows, 'all', ' destination ', 'name').map(row => row.tag)).toEqual(['#B'])
    expect(filterDashboardRows(rows, 'all', '#a', 'name').map(row => row.tag)).toEqual(['#A'])
  })
  it('preserves available selection but drops newly signed-up or unlinked accounts on refresh', () => {
    expect(availableSelection(['#A', '#B', '#REMOVED'], rows)).toEqual(['#A'])
    expect(availableSelection(['#A'], dashboardRows(accounts, [], []))).toEqual(['#A'])
  })
})
