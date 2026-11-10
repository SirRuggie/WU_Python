import { expect, it } from 'vitest'
import {
  currentWarStateLabel,
  displayTrackingStatus,
  needsReviewCount,
  trackingIssues,
  trackingStatusLabel,
  trackingSummary,
  type ClanTracking,
} from './strikeTracking'

const clan = (
  status: ClanTracking['status'],
  fields: Partial<ClanTracking> = {},
): ClanTracking => ({
  clan_tag: '#P2Y',
  clan_name: 'Edrag Rush',
  status,
  current_war_state: 'notInWar',
  latest_recorded_war_at: null,
  ...fields,
})

it('counts every health state without claiming an unverified empty scan is healthy', () => {
  expect(trackingSummary([clan('healthy')])).toEqual({
    label: '1 clan on track',
    tone: 'healthy',
  })
  expect(
    trackingSummary([clan('healthy', { current_war_state: 'unknown' })]),
  ).toEqual({ label: '1 unverified', tone: 'warning' })
  expect(
    trackingSummary([clan('healthy', { current_war_state: undefined })]),
  ).toEqual({ label: '1 unverified', tone: 'warning' })
  expect(
    trackingSummary([
      clan('healthy'),
      clan('behind'),
      clan('private'),
      clan('error'),
    ]),
  ).toEqual({
    label: '1 on track · 1 behind · 1 private · 1 error',
    tone: 'warning',
  })
  expect(trackingSummary([])).toEqual({
    label: 'No clans tracked',
    tone: 'unknown',
  })
  expect(
    displayTrackingStatus(
      clan('healthy', {
        current_war_state: 'preparation',
        latest_recorded_war_at: '2026-10-27T12:00:00Z',
      }),
    ),
  ).toBe('healthy')
})

it('names the official war state and health with explicit text', () => {
  expect(trackingStatusLabel('behind')).toBe('Behind')
  expect(trackingStatusLabel('private')).toBe('War log private')
  expect(trackingStatusLabel('error')).toBe('Error')
  expect(trackingStatusLabel('unverified')).toBe('Unverified')
  expect(currentWarStateLabel('inWar')).toBe('In war')
  expect(currentWarStateLabel('warEnded')).toBe('War ended')
  expect(currentWarStateLabel('private')).toBe('War log private')
  expect(currentWarStateLabel('unknown')).toBe('Unknown')
  expect(currentWarStateLabel()).toBe('Unknown')
})

it('retains deferred and skipped issue descriptions', () => {
  expect(
    trackingIssues(clan('behind', { deferred_accounts: 1, skipped_wars: 0 })),
  ).toBe('1 account needs review')
  expect(
    trackingIssues(clan('behind', { deferred_accounts: 2, skipped_wars: 1 })),
  ).toBe('2 accounts need review · 1 skipped war')
})

it('treats idle as fine and counts only real problems as need review', () => {
  expect(
    trackingSummary([clan('healthy'), clan('idle'), clan('idle')]),
  ).toEqual({
    label: '1 on track · 2 idle',
    tone: 'healthy',
  })
  expect(trackingSummary([clan('idle')])).toEqual({
    label: '1 idle',
    tone: 'healthy',
  })
  expect(trackingSummary([clan('idle'), clan('behind')])).toEqual({
    label: '1 idle · 1 behind',
    tone: 'warning',
  })
  expect(trackingStatusLabel('idle')).toBe('Idle')
  expect(displayTrackingStatus(clan('idle'))).toBe('idle')
  expect(
    needsReviewCount([
      clan('healthy'),
      clan('idle'),
      clan('behind'),
      clan('error'),
      clan('private'),
      clan('healthy', { current_war_state: 'unknown' }),
    ]),
  ).toBe(4)
})
