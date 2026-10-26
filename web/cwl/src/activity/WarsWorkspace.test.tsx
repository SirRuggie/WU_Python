import { beforeEach, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import WarsWorkspace, { WarCard } from './WarsWorkspace'
import type { ClanActivity } from './useClanActivity'
const state = vi.hoisted(() => ({data: null as unknown, error: '', busy: false}))
vi.mock('./useClanActivity', () => ({useClanActivity: () => ({...state, refresh: vi.fn()})}))
vi.mock('./useClock', () => ({useClock: () => 0}))
const side = {tag: '#A', name: 'Our clan', stars: 12, destruction: 8.9, attacks: 4}
const clan: ClanActivity = {tag: '#A', name: 'Our clan', current_member: true, accounts: [{tag: '#P', name: 'Player'}], regular: {state: 'inWar', clan: side, opponent: {...side, tag: '#B', name: 'Their clan', stars: 3}, ends_at: 3600, starts_at: 1, attacks_total: 90, my_accounts: [{tag: '#P', name: '<Player>', attacks_left: 1, attacks_total: 2}]}}
beforeEach(() => {state.data = {scope: 'mine', clans: [clan], warnings: []}; state.error = ''; state.busy = false})
it('keeps personal attack counts visible and secondary dates/actions inside details', () => {
  const html = renderToStaticMarkup(<WarCard clan={clan} type="regular" scope="mine" now={0} onTasks={vi.fn()}/> )
  expect(html).toContain('1 of 2 attacks left')
  expect(html).toContain('&lt;Player&gt;')
  expect(html.indexOf('attacks left')).toBeLessThan(html.indexOf('<details'))
  expect(html.indexOf('Battle starts')).toBeGreaterThan(html.indexOf('<details'))
  expect(html).toContain('View my tasks')
})
it('offers all clans only to staff and keeps current wars separate from inactive clans', () => {
  state.data = {scope: 'mine', warnings: [], clans: [clan, {tag: '#Q', name: 'Quiet clan', current_member: true, regular: {state: 'none'}}]}
  const member = renderToStaticMarkup(<WarsWorkspace canEdit={false} onTasks={vi.fn()}/> )
  expect(member).not.toContain('Show all clans')
  expect(member).toContain('No active war · 1 clan')
  expect(member.indexOf('Quiet clan')).toBeGreaterThan(member.indexOf('class="war-inactive"'))
  expect(renderToStaticMarkup(<WarsWorkspace canEdit onTasks={vi.fn()}/>)).toContain('Show all clans')
})
it('never hides failed lookups inside the inactive disclosure', () => {
  state.data = {scope: 'mine', warnings: [], clans: [{tag: '#E', name: 'Unknown clan', regular: {state: 'error'}}]}
  const html = renderToStaticMarkup(<WarsWorkspace canEdit={false} onTasks={vi.fn()}/> )
  expect(html).toContain('Could not check this war')
  expect(html).not.toContain('war-inactive')
  expect(html).not.toContain('No active wars')
})
it('does not show former CWL hosts in regular wars and explains CWL participation', () => {
  const host = {...clan, current_member: false, cwl: clan.regular}
  state.data = {scope: 'mine', warnings: [], clans: [host]}
  expect(renderToStaticMarkup(<WarsWorkspace canEdit={false} onTasks={vi.fn()}/>)).not.toContain('Your accounts in this war')
  expect(renderToStaticMarkup(<WarsWorkspace canEdit={false} initialType="cwl" onTasks={vi.fn()}/>)).toContain('CWL hosting clan')
})
