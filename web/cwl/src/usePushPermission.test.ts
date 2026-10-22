import { afterEach, expect, it, vi } from 'vitest'
import { observePushPermission } from './usePushPermission'

afterEach(() => vi.unstubAllGlobals())
function environment(query: () => Promise<unknown>) {
  const win = new EventTarget(), doc = Object.assign(new EventTarget(), { visibilityState: 'visible' })
  vi.stubGlobal('window', win); vi.stubGlobal('document', doc)
  vi.stubGlobal('navigator', { permissions: { query } })
  return { win, doc }
}
it('observes a later site-control grant and stops observing on unmount', async () => {
  const permission = new EventTarget(), changed = vi.fn()
  const { win, doc } = environment(vi.fn().mockResolvedValue(permission))
  const stop = observePushPermission(changed)
  await Promise.resolve()
  changed.mockClear()
  permission.dispatchEvent(new Event('change'))
  win.dispatchEvent(new Event('focus'))
  doc.dispatchEvent(new Event('visibilitychange'))
  expect(changed).toHaveBeenCalledTimes(3)
  stop()
  permission.dispatchEvent(new Event('change')); win.dispatchEvent(new Event('focus'))
  expect(changed).toHaveBeenCalledTimes(3)
})
it('retains focus recovery when querying notifications is unsupported', async () => {
  const changed = vi.fn()
  const { win } = environment(vi.fn().mockRejectedValue(new Error('Unsupported')))
  const stop = observePushPermission(changed)
  await Promise.resolve(); await Promise.resolve()
  win.dispatchEvent(new Event('pageshow'))
  expect(changed).toHaveBeenCalledOnce()
  stop()
})
it('ignores a late permission query after leaving the screen', async () => {
  let resolve!: (value: EventTarget) => void
  const changed = vi.fn(), permission = new EventTarget()
  environment(() => new Promise(done => { resolve = done }))
  const stop = observePushPermission(changed); stop(); resolve(permission)
  await Promise.resolve()
  permission.dispatchEvent(new Event('change'))
  expect(changed).not.toHaveBeenCalled()
})
