import { expect, it } from 'vitest'
import { detailQuery, strikeBadge, warMatchup } from './strikeHistoryView'

it('shows exempt records clearly even when the ledger kind is miss', () => {
  expect(strikeBadge('miss', 'exempt')).toBe('Exempt')
  expect(strikeBadge('miss', 'recorded')).toBe('One missed')
  expect(strikeBadge('strike', 'active')).toBe('Active strike')
  expect(strikeBadge('completed', 'completed')).toBe('Attacks done')
})

it('names both sides of a war', () => {
  expect(warMatchup('Warriors United', 'Edrag Rush')).toBe('Warriors United vs Edrag Rush')
})

it('requests all records for an exact war and does not restrict an account to its current clan', () => {
  expect(detailQuery(0, 'all', undefined, 'war-123').get('status')).toBe('all')
  expect(detailQuery(0, 'all', undefined, 'war-123').get('war_key')).toBe('war-123')
  const account = detailQuery(1, 'strikes', '#PLAYER')
  expect(account.get('query')).toBe('#PLAYER')
  expect(account.has('clan')).toBe(false)
  expect(account.get('offset')).toBe('25')
})

import { importEmptyText, strikeLinkLabel } from './strikeHistoryView'
it('shows unlinked and unresolved accounts without implying a Discord link', () => {
  expect(strikeLinkLabel(null)).toBe('Not linked')
  expect(strikeLinkLabel('123', null, 'unlinked')).toBe('Not linked')
  expect(strikeLinkLabel('123', 'Ruggie')).toBe('Ruggie')
  expect(strikeLinkLabel('123')).toBe('Discord 123')
  expect(strikeLinkLabel(null, null, 'unknown')).toBe('Link unknown')
})
it('distinguishes deferred records from wars with no missed attacks', () => {
  expect(importEmptyText([], 3)).toBe('No records ready to import.')
  expect(importEmptyText([], 0)).toBe('No missed attacks found in saved wars.')
})

it('does not claim no missed attacks when whole wars could not be checked', () => {
  expect(importEmptyText([], 0, 2)).toBe('No records ready to import.')
})
