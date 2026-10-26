import { beforeEach, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import EventsWorkspace from './EventsWorkspace'
const fixture = vi.hoisted(() => ({now: Date.UTC(2026, 9, 23, 12), data: {scope: 'mine', checked_at: '2026-10-23T12:00:00Z', warnings: [], clans: []} as any, error: ''}))
vi.mock('./useClock', () => ({useClock: () => fixture.now}))
vi.mock('./useClanActivity', () => ({useClanActivity: () => ({data: fixture.data, error: fixture.error, busy: false, refresh: vi.fn()})}))
beforeEach(() => {fixture.now = Date.UTC(2026, 9, 23, 12); fixture.error = ''; fixture.data.clans = []})
it('preserves event order, exact dates, elapsed progress and CWL navigation', () => {
  const html = renderToStaticMarkup(<EventsWorkspace canEdit={false} onWars={vi.fn()}/> )
  const titles = ['Trophy season', 'Clan Games', 'Raid weekend', 'Clan War Leagues']
  titles.forEach((title, i) => {expect(html).toContain(title); if (i) expect(html.indexOf(title)).toBeGreaterThan(html.indexOf(titles[i - 1]))})
  expect(html).toContain('2026-10-22T08:00:00.000Z')
  expect(html).toContain('Clan Games time elapsed')
  expect(html).toContain('Signup opens')
  expect(html).toContain('View clan battle schedules')
  expect(html).toContain('Show UTC')
  expect(html).not.toContain('Family clans')
})
it('switches CWL signup labels at the opening boundary without calling it battle time', () => {
  fixture.now = Date.UTC(2026, 10, 1, 8)
  const html = renderToStaticMarkup(<EventsWorkspace canEdit onWars={vi.fn()}/> )
  expect(html).toContain('Signup open')
  expect(html).toContain('Signup closes')
  expect(html).toContain('not a fixed end date')
  expect(html).toContain('Family clans')
})
it('retains unavailable raid status instead of implying zero or no activity', () => {
  fixture.data.clans = [{tag: '#ABC', name: '<Sample>', raid: {state: 'error'}}]
  fixture.error = 'Could not refresh'
  const html = renderToStaticMarkup(<EventsWorkspace canEdit={false} onWars={vi.fn()}/> )
  expect(html).toContain('&lt;Sample&gt;')
  expect(html).toContain('This does not mean it has not started')
  expect(html).toContain('Could not refresh')
  expect(html).toContain('Showing the last update')
})
