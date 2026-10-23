import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ServerSettingsIndex, { settingsCategory } from './ServerSettingsIndex'
import type { ManagementSection } from './serverManagement'
const sections: ManagementSection[] = [
  {
    id: 'band_monitor',
    label: 'BAND monitor',
    description: 'Calendar connection',
    group: 'War',
  },
  {
    id: 'fwa_sync',
    label: 'Sync reminders',
    description: 'Signup channel',
    group: 'War',
  },
  {
    id: 'fwa_bases',
    label: 'Base links',
    description: 'Town Hall guidance',
    group: 'War',
  },
  {
    id: 'hidden',
    label: 'Restricted tool',
    description: 'No access',
    group: 'War',
    allowed: false,
  },
]
const render = (query = '') =>
  renderToStaticMarkup(
    <ServerSettingsIndex
      sections={sections}
      query={query}
      onQuery={() => {}}
      onOpen={() => {}}
    />,
  )
it('groups existing tools by purpose and excludes denied tools', () => {
  const html = render()
  expect(html).toContain('Connections')
  expect(html).toContain('Monitoring &amp; reminders')
  expect(html).toContain('Clan resources')
  expect(html).not.toContain('Restricted tool')
  expect(html).not.toContain('Connected')
})
it('search works across categories and provides distinct no-match recovery', () => {
  expect(render('calendar')).toContain('BAND monitor')
  expect(render('calendar')).not.toContain('Base links')
  expect(render('absent')).toContain('Clear search')
  expect(render('absent')).toContain('No settings match this search.')
})
it('does not invent empty or health states', () => {
  const html = renderToStaticMarkup(
    <ServerSettingsIndex
      sections={[]}
      query=""
      onQuery={() => {}}
      onOpen={() => {}}
    />,
  )
  expect(html).toContain('No settings are available for your access.')
  expect(html).not.toContain('Clear search')
  expect(settingsCategory({ ...sections[0], id: 'war--win' })).toBe(
    'War messages',
  )
})

it('keeps long setting groups collapsed until opened or searched', () => {
  const messages = Array.from({length: 6}, (_, index) => ({
    id: `war--${index}`, label: `War message ${index}`, description: 'War notice', group: 'War',
  }))
  const props = {sections: messages, onQuery: () => {}, onOpen: () => {}}
  const browse = renderToStaticMarkup(<ServerSettingsIndex {...props} query="" />)
  const search = renderToStaticMarkup(<ServerSettingsIndex {...props} query="War" />)
  expect(browse).toContain('<details>')
  expect(browse).not.toContain('<details open')
  expect(search).toContain('<details open="">')
  expect(search).toContain('War message 5')
})
