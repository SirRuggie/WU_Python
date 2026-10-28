import { describe, expect, it } from 'vitest'
import { clanDeepLink, draftPublicationStatus, memberPlacementStatus, type MyAssignments, type PublicationDraft } from './publication'
const draft: PublicationDraft = { last_publication: null, next_version: 1, draft_revision: 8, draft_changed: false, preview: { accounts: [], clans: [], assigned_count: 0, unassigned_count: 0 }, published: null }
describe('roster publication', () => {
  it('encodes Clash clan tags in a deep link', () => { expect(clanDeepLink('#Q2 R')).toBe('https://link.clashofclans.com/en?action=OpenClanProfile&tag=%23Q2%20R') })
  it('labels current placements provisional until an unchanged version is published', () => {
    const assignments: MyAssignments = { published: null, accounts: [], visibility: 'current', draft_changed: false }
    expect(memberPlacementStatus(assignments)).toBe('provisional')
    const published = { version: 1, published_at: '2026-10-14T00:00:00Z', joining_instructions: '' }
    expect(memberPlacementStatus({ ...assignments, published, draft_changed: false })).toBe('official')
    expect(memberPlacementStatus({ ...assignments, published, draft_changed: true })).toBe('provisional')
  })
  it('distinguishes unpublished, current and changed drafts', () => {
    expect(draftPublicationStatus(draft)).toBe('unpublished')
    const published = { version: 2, revision: 8, published_at: '2026-10-14T00:00:00Z', published_by: '1', joining_instructions: '', assigned_count: 0, unassigned_count: 0 }
    expect(draftPublicationStatus({ ...draft, draft_revision: 9, published })).toBe('current')
    expect(draftPublicationStatus({ ...draft, draft_revision: 10, draft_changed: true, published })).toBe('changed')
  })
})
