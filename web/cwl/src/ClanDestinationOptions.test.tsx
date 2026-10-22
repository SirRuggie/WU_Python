import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ClanDestinationOptions from './ClanDestinationOptions'
import type { RosterClan } from './roster'
const host = (tag: string, pool: RosterClan['pool'], archived = false): RosterClan => ({
  tag, name: tag, pool, archived, capacity: 15, effective_capacity: 15,
  assigned_count: 0, min_weight: null, max_weight: null, lower_league: null,
})
const clans = [host('Main host', 'main'), host('Lazy host', 'lazy'), host('Uncategorized', null), host('Archived', 'lazy', true)]
describe('Lazy hosting destinations', () => {
  it('shows only active Lazy hosts', () => {
    const html = renderToStaticMarkup(<select><ClanDestinationOptions clans={clans} pool="lazy"/></select>)
    expect(html).toContain('Lazy host')
    for (const name of ['Main host', 'Uncategorized', 'Archived', 'Main CWL', 'Group not set']) expect(html).not.toContain(name)
  })
  it('preserves an existing out-of-group placement without offering it as a destination', () => {
    const html = renderToStaticMarkup(<select><ClanDestinationOptions clans={clans} pool="lazy" current="Main host"/></select>)
    expect(html).toContain('disabled="">Current placement (not a Lazy host)')
    expect(html).not.toContain('Main CWL')
  })
  it('keeps Main behavior and full-clan protection', () => {
    const html = renderToStaticMarkup(<select><ClanDestinationOptions clans={[...clans, {...host('Full Lazy', 'lazy'), assigned_count:15}]} pool="main"/></select>)
    expect(html).toContain('Main CWL')
    expect(html).toContain('Lazy CWL')
    expect(html).toContain('value="Full Lazy" disabled=""')
  })
})
