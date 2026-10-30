import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { isValidElement, type ReactNode } from 'react'
const hooks = vi.hoisted(() => ({
  index: 0,
  ref: 0,
  values: [] as unknown[],
  refs: [] as { current: unknown }[],
}))
const transport = vi.hoisted(() => vi.fn())
vi.mock('react', async (original) => ({
  ...(await original<typeof import('react')>()),
  useState: (initial: unknown) => {
    const i = hooks.index++
    if (!(i in hooks.values))
      hooks.values[i] =
        typeof initial === 'function' ? (initial as () => unknown)() : initial
    return [
      hooks.values[i],
      (next: unknown) => {
        hooks.values[i] =
          typeof next === 'function'
            ? (next as (old: unknown) => unknown)(hooks.values[i])
            : next
      },
    ]
  },
  useRef: (initial: unknown) =>
    hooks.refs[hooks.ref++] ??
    (hooks.refs[hooks.ref - 1] = { current: initial }),
  useEffect: () => {},
}))
vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: transport,
}))
import CommandTest from './CommandTest'
import type { Command } from './CommandBuilder'
const draft = {
  command: '!welcome',
  text: 'Welcome',
  title: '',
  description: '',
  image_url: '',
  blocks: [],
  color: '#ffffff',
  enabled: true,
  delete_trigger: true,
  last_delete_error: {
    at: '2026-10-30T00:00:00Z',
    channel_id: '123',
    reason: 'Missing Manage Messages',
  },
} as Command
function elements(
  node: ReactNode,
): { type: unknown; props: Record<string, unknown> }[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [
    { type: node.type, props: node.props },
    ...elements(node.props.children as ReactNode),
  ]
}
function draw() {
  hooks.index = 0
  hooks.ref = 0
  return elements(CommandTest({ draft, disabled: false, onBusy: vi.fn() }))
}
function click(label: string) {
  const button = draw().find(
    (node) => node.type === 'button' && node.props.children === label,
  )!
  expect(button).toBeDefined()
  return (button.props.onClick as () => void)()
}
beforeEach(() => {
  hooks.values = []
  hooks.refs = []
  transport.mockReset()
})
afterEach(() => vi.unstubAllGlobals())
it('does not fetch channels or send while the test disclosure is closed', () => {
  draw()
  expect(transport).not.toHaveBeenCalled()
})
it('requires review and rejects duplicate synchronous sends', async () => {
  hooks.values = [
    [{ id: '123', name: 'test' }],
    '123',
    false,
    false,
    '',
    '',
    '',
    false,
    true,
  ]
  let resolve!: (value: unknown) => void
  transport.mockReturnValue(
    new Promise((done) => {
      resolve = done
    }),
  )
  const send = draw().find(
    (node) => node.type === 'button' && node.props.children === 'Send test now',
  )!
  ;(send.props.onClick as () => void)()
  ;(send.props.onClick as () => void)()
  expect(transport).toHaveBeenCalledTimes(1)
  expect(transport.mock.calls[0][2].values.delete_trigger).toBe(true)
  expect(transport.mock.calls[0][2].values).not.toHaveProperty(
    'last_delete_error',
  )
  resolve({ url: 'https://discord.com/test' })
  await Promise.resolve()
  await Promise.resolve()
  expect(hooks.values[6]).toBe('https://discord.com/test')
})
it('uncertain delivery blocks send until explicitly acknowledged', async () => {
  hooks.values = [
    [{ id: '123', name: 'test' }],
    '123',
    false,
    false,
    '',
    '',
    '',
    false,
    true,
  ]
  transport.mockRejectedValue(new Error('Connection lost'))
  click('Send test now')
  await Promise.resolve()
  await Promise.resolve()
  expect(hooks.values[7]).toBe(true)
  const review = draw().find(
    (node) => node.type === 'button' && node.props.children === 'Review test',
  )!
  expect(review.props.disabled).toBe(true)
  expect(transport).toHaveBeenCalledTimes(1)
  click('I checked Discord — prepare a new test')
  expect(hooks.values[7]).toBe(false)
  expect(transport).toHaveBeenCalledTimes(1)
})
