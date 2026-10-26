import { expect, it, vi } from 'vitest'
import { dashboardSearchAttention } from './dashboardSearchAttention'

it('keeps account and staff-directory failures visible with one shared refresh action', () => {
  const onRefresh = vi.fn()
  const items = dashboardSearchAttention('account read failed', 'directory read failed', false, onRefresh)
  expect(items.map(item => item.title)).toEqual(['Linked accounts are unavailable', 'Staff family clan directory is unavailable'])
  expect(items.filter(item => item.action)).toHaveLength(1)
  expect(items[0].action?.label).toBe('Refresh search data')
  items[0].action?.onClick()
  expect(onRefresh).toHaveBeenCalledOnce()
})

it('labels revoked access distinctly and lets a directory-only failure retry', () => {
  const onRefresh = vi.fn()
  expect(dashboardSearchAttention('Your dashboard access changed. Refresh or sign in again.', '', false, onRefresh)[0].title).toBe('Dashboard access changed')
  expect(dashboardSearchAttention('', 'directory unavailable', false, onRefresh)[0].action?.label).toBe('Refresh search data')
})
