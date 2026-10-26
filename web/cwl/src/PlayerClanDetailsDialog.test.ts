import { describe, expect, it } from 'vitest'
import { detailsFreshnessText, safeClanBadgeUrl } from './PlayerClanDetailsDialog'

describe('read-only player and clan details', () => {
  it('accepts only official HTTPS clan badge assets', () => {
    const badge = 'https://api-assets.clashofclans.com/badges/200/example.png'
    expect(safeClanBadgeUrl(badge)).toBe(badge)
    for (const value of [
      'javascript:alert(1)', 'data:image/svg+xml,<svg onload=alert(1)>',
      'http://api-assets.clashofclans.com/badges/200/example.png',
      'https://api-assets.clashofclans.com.evil.test/badges/200/example.png',
      'https://api-assets.clashofclans.com:444/badges/200/example.png',
      'https://api-assets.clashofclans.com/private/example.png',
      'https://api-assets.clashofclans.com/badges/example.png?token=secret',
      '//api-assets.clashofclans.com/badges/example.png',
    ]) expect(safeClanBadgeUrl(value), value).toBeNull()
  })

  it('labels a saved or partial read without claiming live source verification', () => {
    expect(detailsFreshnessText('player', 'saved')).toContain('saved player data')
    expect(detailsFreshnessText('clan', 'partial')).toContain('Clan details are still loading')
    expect(detailsFreshnessText('clan', 'current')).toContain('latest available read')
    expect(detailsFreshnessText('player', 'unavailable')).toContain('unavailable')
    expect(detailsFreshnessText('clan', 'unavailable')).toBe('Some clan details could not be refreshed.')
    expect(detailsFreshnessText('player', 'current', 'invalid-date')).not.toContain('Invalid Date')
  })
})
