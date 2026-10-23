import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, setCsrfToken, reportBrowserIssue } from './api'

afterEach(() => { vi.unstubAllGlobals(); setCsrfToken('') })
describe('safe issue feedback', () => {
  it('preserves API reason and includes the server reference', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({error:'Game data unavailable',issue_reference:'abc123'}), {status:503,headers:{'X-Read-Retries-Exhausted':'1'}})))
    await expect(api('/accounts')).rejects.toThrow('Game data unavailable Reference: abc123')
  })
  it('does not report browser problems before authentication', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch',fetch)
    await reportBrowserIssue('browser_error')
    expect(fetch).not.toHaveBeenCalled()
  })
  it('sends only a fixed error category with CSRF and never retries an action', async () => {
    const fetch = vi.fn().mockRejectedValue(new Error('offline'))
    vi.stubGlobal('fetch',fetch)
    setCsrfToken('sample')
    await reportBrowserIssue('browser_error')
    await reportBrowserIssue('browser_error')
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][1].body).toBe('{"kind":"browser_error"}')
    expect(fetch.mock.calls[0][1].headers['X-CSRF-Token']).toBe('sample')
  })
})
