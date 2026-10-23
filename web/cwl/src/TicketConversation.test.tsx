import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
const hooks = vi.hoisted(() => ({
  index: 0,
  setters: [] as ReturnType<typeof vi.fn>[],
  effects: [] as (() => void | (() => void))[],
}))
const transport = vi.hoisted(() => vi.fn())
vi.mock('react', async (original) => {
  const actual = await original<typeof import('react')>()
  return {
    ...actual,
    useState: (initial: unknown) => {
      const index = hooks.index++
      const setter = vi.fn()
      hooks.setters[index] = setter
      return [initial, setter]
    },
    useEffect: (effect: () => void | (() => void)) =>
      hooks.effects.push(effect),
  }
})
vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: transport,
}))
import { ApiError } from './api'
import TicketConversation from './TicketConversation'
const ticket = {
  id: 'one',
  number: 1,
  name: 'Sample',
  user_id: '123',
  kind: 'main',
  status: 'open',
  created_at: null,
  flags: [],
}
const result = {
  ticket,
  messages: [],
  older: null,
  discord_url: 'https://discord.com/channels/1/2',
  archived: false,
  checked_at: 1,
}
function mount() {
  renderToStaticMarkup(<TicketConversation ticket={ticket} onBack={() => {}} />)
  return hooks.effects[1]() as () => void
}
beforeEach(() => {
  hooks.index = 0
  hooks.setters = []
  hooks.effects = []
  transport.mockReset()
  vi.useFakeTimers()
  vi.stubGlobal('document', { hidden: false })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('ignores a conversation response after leaving the reader', async () => {
  let resolve!: (value: unknown) => void
  transport.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const cleanup = mount()
  cleanup()
  resolve(result)
  await Promise.resolve()
  await Promise.resolve()
  expect(hooks.setters[2]).not.toHaveBeenCalledWith(result)
  await vi.advanceTimersByTimeAsync(60000)
  expect(transport).toHaveBeenCalledTimes(1)
})
it('clears protected content and stops automatic polling after permission loss', async () => {
  transport.mockRejectedValue(new ApiError('No access', 403))
  const cleanup = mount()
  await vi.advanceTimersByTimeAsync(0)
  expect(hooks.setters[2]).toHaveBeenCalledWith(null)
  expect(hooks.setters[8]).toHaveBeenCalledWith(true)
  await vi.advanceTimersByTimeAsync(60000)
  expect(transport).toHaveBeenCalledTimes(1)
  cleanup()
})
it('avoids overlapping or background conversation refreshes', async () => {
  let resolve!: (value: unknown) => void
  transport.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const cleanup = mount()
  await vi.advanceTimersByTimeAsync(60000)
  expect(transport).toHaveBeenCalledTimes(1)
  resolve(result)
  await vi.advanceTimersByTimeAsync(0)
  vi.stubGlobal('document', { hidden: true })
  await vi.advanceTimersByTimeAsync(60000)
  expect(transport).toHaveBeenCalledTimes(1)
  cleanup()
})
