import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadTasks } from './todoLoading'
import { api } from './api'
vi.mock('./api', () => ({ api: vi.fn() }))
afterEach(() => { vi.resetAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals() })
describe('progressive Tasks reads', () => {
  it('shows completed sections before the overall job finishes', async () => {
    vi.useFakeTimers(); vi.stubGlobal('document', { hidden: false })
    const partial = { accounts: [], views: { war: { ok: true }, cwl: { loading: true } } }
    const complete = { accounts: [], views: { war: { ok: true }, cwl: { ok: true } } }
    vi.mocked(api).mockResolvedValueOnce({ snapshot: partial, updating: true }).mockResolvedValueOnce({ snapshot: complete, updating: false })
    const progress = vi.fn()
    const work = loadTasks(progress, () => true)
    await vi.advanceTimersByTimeAsync(0)
    expect(progress).toHaveBeenCalledWith(partial, true)
    await vi.advanceTimersByTimeAsync(750); await work
    expect(progress).toHaveBeenLastCalledWith(complete, false)
    expect(api).toHaveBeenCalledTimes(2)
  })
  it('stops on a terminal error rather than restarting failed work', async () => {
    vi.stubGlobal('document', { hidden: false })
    vi.mocked(api).mockResolvedValue({ snapshot: null, updating: false, error: 'Unavailable' })
    await expect(loadTasks(vi.fn(), () => true)).rejects.toThrow('Unavailable')
    expect(api).toHaveBeenCalledTimes(1)
  })
  it('ignores responses after leaving the page', async () => {
    vi.stubGlobal('document', { hidden: false })
    let active = true
    vi.mocked(api).mockImplementation(async () => { active = false; return { snapshot: {}, updating: false } })
    const progress = vi.fn()
    await loadTasks(progress, () => active)
    expect(progress).not.toHaveBeenCalled()
  })
})
