import { expect, it } from 'vitest'
import { trackingIssues, trackingStatusLabel, trackingSummary, type ClanTracking } from './strikeTracking'
const clan = (status: ClanTracking['status']): ClanTracking => ({ clan_tag: '#P2Y', clan_name: 'Edrag Rush', status })
it('keeps healthy tracking quiet and flags delayed or review clans', () => {
  expect(trackingSummary([clan('healthy')])).toEqual({ label: '1 clan on track', tone: 'healthy' })
  expect(trackingSummary([clan('delayed')])).toEqual({ label: '1 clan delayed', tone: 'warning' })
  expect(trackingSummary([clan('needs_review'), clan('delayed')])).toEqual({ label: '1 clan needs review · 1 delayed', tone: 'warning' })
  expect(trackingStatusLabel('needs_review')).toBe('Needs review')
})

it('omits zero tracking issues and uses clear singular labels', () => {
  expect(trackingIssues({ ...clan('needs_review'), deferred_accounts: 1, skipped_wars: 0 })).toBe('1 account needs review')
  expect(trackingIssues({ ...clan('needs_review'), deferred_accounts: 2, skipped_wars: 1 })).toBe('2 accounts need review · 1 skipped war')
})
