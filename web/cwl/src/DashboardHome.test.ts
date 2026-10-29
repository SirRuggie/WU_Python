import { describe, expect, it } from 'vitest'
import type { Season } from './api'
import { homeAttentionState, homeNextStep } from './DashboardHome'

const season = (signup_open: boolean) => ({ signup_open, status: 'draft', label: 'November CWL' }) as Season

describe('Home next step', () => {
  it('withholds account counts and actions while account or signup data is incomplete', () => {
    expect(homeNextStep(false, season(true), 1, 1)).toMatchObject({ title: 'Checking your CWL status', destination: null })
    expect(homeNextStep(false, season(true), 1, 1, 'saved')).toMatchObject({ title: 'Checking saved CWL status', destination: null })
  })

  it('reassures partially signed members with the same counts as assignments', () => {
    expect(homeNextStep(true, season(true), 3, 2)).toMatchObject({
      title: "✓ You're signed up · 1 of 3 accounts",
      destination: 'assignments',
      detail: "We've got your signup. Your clan will show here once staff finish the roster.",
    })
  })

  it('keeps closed-season and empty-account paths distinct', () => {
    expect(homeNextStep(true, season(false), 2, 0).destination).toBe('assignments')
    expect(homeNextStep(true, { ...season(true), status: 'active' }, 2, 1).destination).toBe('assignments')
    expect(homeNextStep(true, season(true), 0, 0).destination).toBe('help')
    expect(homeNextStep(true, undefined, 2, 2).destination).toBe(null)
  })
})

describe('Home attention states', () => {
  it('requires a complete empty read before suggesting account linking', () => {
    expect(homeAttentionState(false, '', false, 0)).toBeNull()
    expect(homeAttentionState(false, '', true, 0)).toBeNull()
    expect(homeAttentionState(true, '', true, 0)).toMatchObject({ kind: 'empty', actionLabel: 'Link accounts' })
    expect(homeAttentionState(true, '', true, 2)).toBeNull()
  })

  it('keeps a failed read distinct from a confirmed empty account', () => {
    expect(homeAttentionState(false, 'Provider unavailable', false, 0)).toMatchObject({ kind: 'error', title: 'Could not refresh your dashboard', detail: 'Provider unavailable', actionLabel: 'Refresh' })
    expect(homeAttentionState(false, 'Provider unavailable', true, 0)?.detail).toContain('may be out of date')
  })
})
