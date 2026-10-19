import { describe, expect, it } from 'vitest'
import { initialAssignmentTarget, parseAssignmentTarget, rememberAssignmentTarget } from './assignmentLink'
describe('assignment deep link', () => {
  it('accepts only assignment view with a numeric season', () => {
    expect(parseAssignmentTarget('?view=assignments&season=12')).toEqual({ season: '12' })
    expect(parseAssignmentTarget('?view=staff&season=12')).toBeNull()
    expect(parseAssignmentTarget('?view=assignments&season=../../x')).toBeNull()
  })
  it('restores assignment target once after OAuth returns to the root', () => {
    const entries = new Map<string, string>()
    const storage = { setItem: (key: string, value: string) => { entries.set(key, value) }, getItem: (key: string) => entries.get(key) || null, removeItem: (key: string) => { entries.delete(key) } }
    rememberAssignmentTarget('?view=assignments&season=7', storage)
    expect(initialAssignmentTarget('', storage)).toEqual({ season: '7' })
    expect(initialAssignmentTarget('', storage)).toBeNull()
  })
})
