import { describe, expect, it } from 'vitest'
import type { Season } from './api'
import { homeNextStep } from './DashboardHome'

const season = (signup_open: boolean) => ({ signup_open, status: 'draft', label: 'November CWL' }) as Season

describe('Home next step', () => {
  it('withholds account counts and actions while account or signup data is incomplete', () => {
    expect(homeNextStep(false, season(true), 1, 1)).toMatchObject({ title: 'Checking your CWL status', destination: null })
    expect(homeNextStep(false, season(true), 1, 1, 'saved')).toMatchObject({ title: 'Checking saved CWL status', destination: null })
    expect(homeNextStep(false, season(true), 1, 1, 'error')).toMatchObject({ title: 'Could not check CWL status', destination: null })
  })

  it('directs fresh unsigned accounts to signup review', () => {
    expect(homeNextStep(true, season(true), 3, 2)).toMatchObject({
      title: '2 accounts to sign up',
      destination: 'signup',
      detail: 'Choose Main or Lazy for your accounts, then review before saving.',
    })
  })

  it('keeps closed-season and empty-account paths distinct', () => {
    expect(homeNextStep(true, season(false), 2, 0).destination).toBe('assignments')
    expect(homeNextStep(true, { ...season(true), status: 'active' }, 2, 1).destination).toBe('assignments')
    expect(homeNextStep(true, season(true), 0, 0).destination).toBe('help')
    expect(homeNextStep(true, undefined, 2, 2).destination).toBe(null)
  })
})
