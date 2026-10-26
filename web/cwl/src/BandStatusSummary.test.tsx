import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import BandStatusSummary, { bandStatusWarning } from './BandStatusSummary'
import type { ManagementField } from './serverManagement'

const field = (
  key: string,
  label: string,
  value: string | boolean,
): ManagementField => ({
  key,
  label,
  value,
  type: typeof value === 'boolean' ? 'boolean' : 'text',
})

const status = [
  field('task', 'Monitor', 'Running'),
  field('checked_at', 'Last status check', '2026-10-26T12:00:00Z'),
  field('startup', 'Startup', '✅ Healthy'),
  field('key', 'BAND connection', 'Configured'),
  field('health', 'Poll health', 'failed'),
  field('last_success', 'Last successful check', '2026-10-25T12:00:00Z'),
  field('last_error', 'Last recorded problem', 'band_request_failed'),
  field('debug', 'Debug logging', false),
]

describe('BAND status summary', () => {
  it('keeps the recorded problem and check time visible while disclosing technical details', () => {
    const html = renderToStaticMarkup(<BandStatusSummary fields={status} />)
    const disclosure = html.indexOf('<details')
    expect(html.indexOf('Last recorded problem')).toBeLessThan(disclosure)
    expect(html.indexOf('Last status check')).toBeLessThan(disclosure)
    expect(html.indexOf('Poll health')).toBeLessThan(disclosure)
    expect(html.indexOf('Startup')).toBeGreaterThan(disclosure)
    expect(html).toContain('<summary>Technical status details</summary>')
    expect(html).not.toContain('Next scheduled')
  })

  it('formats known timestamps with a timezone and preserves malformed or unknown values', () => {
    const html = renderToStaticMarkup(
      <BandStatusSummary
        fields={status.map((item) =>
          item.key === 'last_success'
            ? { ...item, value: '2026-02-30T12:00:00Z' }
            : item,
        )}
      />,
    )
    expect(html).toContain('<time dateTime="2026-10-26T12:00:00Z">')
    expect(html).toMatch(/<time[^>]+>[^<]*(?:UTC|GMT|[A-Z]{2,5})<\/time>/)
    expect(html).toContain('2026-02-30T12:00:00Z')
    expect(html).not.toContain('<time dateTime="2026-02-30T12:00:00Z">')

    const unknown = renderToStaticMarkup(
      <BandStatusSummary
        fields={status.map((item) =>
          item.key === 'checked_at' ? { ...item, value: 'Not checked' } : item,
        )}
      />,
    )
    expect(unknown).toContain('Not checked')
  })

  it('shortens only the known fresh BAND warning', () => {
    expect(bandStatusWarning('Use Check status for current bot information. Debug resets when the bot restarts.')).toBe('Check status for current information.')
    expect(bandStatusWarning('Status is outdated or unavailable. Check status before relying on these results.')).toContain('outdated or unavailable')
  })

  it('brings a stopped startup state into the visible summary', () => {
    const html = renderToStaticMarkup(
      <BandStatusSummary
        fields={status.map((item) =>
          item.key === 'startup' ? { ...item, value: '⏹️ Stopped' } : item,
        )}
      />,
    )
    expect(html.indexOf('Startup')).toBeLessThan(html.indexOf('<details'))
    expect(html).toContain('⏹️ Stopped')
  })

  it('shows unavailable fields without implying a healthy connection', () => {
    const html = renderToStaticMarkup(
      <BandStatusSummary
        fields={status.map((item) =>
          ['task', 'key', 'health'].includes(item.key)
            ? { ...item, value: 'Status unavailable' }
            : item,
        )}
      />,
    )
    expect(html).toContain('Status unavailable')
    expect(html).not.toContain('Configured')
    expect(html).toContain('are historical')
  })

  it('preserves all fields from an older response without known BAND keys', () => {
    const html = renderToStaticMarkup(
      <BandStatusSummary fields={[field('legacy', 'Legacy state', 'Unknown')]} />,
    )
    expect(html).toContain('Legacy state')
    expect(html).toContain('Unknown')
  })
})
