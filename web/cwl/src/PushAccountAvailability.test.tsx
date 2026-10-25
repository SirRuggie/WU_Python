import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PushReminders from './PushReminders'
vi.mock('./usePushPermission', () => ({ default: () => ({support:{supported:false,permission:'default',reason:'Test browser'},refreshPermission:vi.fn()}) }))
describe('notification choices during partial account loading', () => {
  it('does not offer to replace saved selections with a partial list or claim accounts are unlinked', () => {
    const html = renderToStaticMarkup(<PushReminders accounts={[]} accountsComplete={false}/>)
    expect(html).toContain('Your saved selections are kept.')
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Select all linked accounts<\/button>/)
    expect(html).not.toContain('Link your Clash accounts to select them here.')
  })
  it('retains normal empty-list guidance after a complete check', () => {
    const html = renderToStaticMarkup(<PushReminders accounts={[]} accountsComplete/> )
    expect(html).toContain('Link your Clash accounts to select them here.')
    expect(html).not.toContain('Your saved selections are kept.')
  })
})
