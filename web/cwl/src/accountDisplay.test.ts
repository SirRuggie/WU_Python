import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { loadAccountDisplay, mergeAccountProgress } from './accountDisplay'
vi.mock('./api', () => ({ api: vi.fn(), ApiError: class extends Error { constructor(message: string, public status: number) { super(message) } } }))
const snapshot = (updating: boolean, error: string | null = null) => ({ accounts: [], updating, error, link_instruction: 'Link help' })
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('document', { hidden: false }); vi.mocked(api).mockReset() })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('publishes partial reads and forces refresh only once', async () => {
  vi.mocked(api).mockResolvedValueOnce(snapshot(true)).mockResolvedValueOnce(snapshot(false))
  const progress = vi.fn()
  const task = loadAccountDisplay(progress, () => true, true)
  await vi.advanceTimersByTimeAsync(0)
  expect(progress).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(750)
  expect((await task).updating).toBe(false)
  expect(api).toHaveBeenNthCalledWith(1, '/linked-accounts?background=1&refresh=1')
  expect(api).toHaveBeenNthCalledWith(2, '/linked-accounts?background=1')
})
it('reports incomplete results as failure after showing the available accounts', async () => {
  vi.mocked(api).mockResolvedValue(snapshot(false, 'Some accounts failed'))
  const progress = vi.fn()
  await expect(loadAccountDisplay(progress, () => true)).rejects.toThrow('Some accounts failed')
  expect(progress).toHaveBeenCalledOnce()
  expect(api).toHaveBeenCalledOnce()
})
it('rejects a response after navigation without updating the abandoned screen', async () => {
  let active = true
  let resolve!: (value: unknown) => void
  vi.mocked(api).mockImplementation(() => new Promise(done => { resolve = done }) as never)
  const progress = vi.fn()
  const task = loadAccountDisplay(progress, () => active).catch(error => error)
  active = false; resolve(snapshot(false))
  expect((await task).name).toBe('AbortError')
  expect(progress).not.toHaveBeenCalled()
})
it('stops immediately on authorization failure', async () => {
  vi.mocked(api).mockRejectedValue(new ApiError('Denied', 403))
  const progress = vi.fn()
  await expect(loadAccountDisplay(progress, () => true)).rejects.toThrow('Denied')
  expect(progress).not.toHaveBeenCalled()
  expect(api).toHaveBeenCalledOnce()
})
it('pauses polling while hidden and has a finite deadline', async () => {
  vi.mocked(api).mockResolvedValue(snapshot(true))
  const task = loadAccountDisplay(() => {}, () => true).catch(error => error)
  await vi.advanceTimersByTimeAsync(0)
  vi.stubGlobal('document', { hidden: true })
  await vi.advanceTimersByTimeAsync(136_000)
  expect((await task).message).toContain('taking longer')
  expect(api).toHaveBeenCalledOnce()
})

it('keeps existing selections visible until a successful complete account list arrives', () => {
  const old = { tag: '#OLD', name: 'Existing selection' } as import('./api').Account
  const fresh = { tag: '#NEW', name: 'New linked account' } as import('./api').Account
  expect(mergeAccountProgress([old], { ...snapshot(true), accounts: [fresh] })).toEqual([old, fresh])
  expect(mergeAccountProgress([old], { ...snapshot(false, 'Offline'), accounts: [] })).toEqual([old])
  expect(mergeAccountProgress([old], { ...snapshot(false), accounts: [fresh] })).toEqual([fresh])
})
