import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const hook = vi.hoisted(() => ({
  states: [] as unknown[],
  refs: [] as { current: number }[],
  stateIndex: 0,
  refIndex: 0,
  cleanup: undefined as (() => void) | undefined,
}))
const transport = vi.hoisted(() => vi.fn())

vi.mock('react', async original => {
  const actual = await original<typeof import('react')>()
  return {
    ...actual,
    useState: (initial: unknown) => {
      const index = hook.stateIndex++
      if (!(index in hook.states)) hook.states[index] = typeof initial === 'function'
        ? (initial as () => unknown)()
        : initial
      return [
        hook.states[index],
        (next: unknown) => {
          hook.states[index] = typeof next === 'function'
            ? (next as (value: unknown) => unknown)(hook.states[index])
            : next
        },
      ]
    },
    useRef: (initial: number) => {
      const index = hook.refIndex++
      hook.refs[index] ||= { current: initial }
      return hook.refs[index]
    },
    useEffect: (effect: () => void | (() => void)) => {
      hook.cleanup?.()
      hook.cleanup = effect() || undefined
    },
  }
})
vi.mock('./api', async original => ({
  ...(await original<typeof import('./api')>()),
  api: transport,
}))

import { ApiError } from './api'
import MemberActivityHistory from './MemberActivityHistory'

const fixture = {
  id: 'event-1',
  user_id: '123456789',
  event_type: 'join' as const,
  display_name: 'Example Member',
  username: 'example',
  avatar_url: '/api/cwl/manage/member-events/event-1/avatar',
  occurred_at: '2026-10-26T12:00:00Z',
  delivery_status: 'sent',
}
function render() {
  hook.stateIndex = 0
  hook.refIndex = 0
  return renderToStaticMarkup(createElement(MemberActivityHistory))
}
function reset() {
  hook.states = []
  hook.refs = []
  hook.stateIndex = 0
  hook.refIndex = 0
  hook.cleanup = undefined
  transport.mockReset()
}

beforeEach(reset)
afterEach(() => {
  hook.cleanup?.()
  hook.cleanup = undefined
})

it('keeps the compact history search and UTC filters visible while loading', () => {
  const html = render()
  expect(html).toContain('<h2 id="member-activity-title">Activity history</h2>')
  expect(html).toContain('Search name or Discord ID')
  expect(html).toContain('Activity')
  expect(html).toContain('<summary>Date range</summary>')
  expect(html).not.toContain('open=""')
  expect(html).toContain('From (UTC)')
  expect(html).toContain('To (UTC)')
  expect(html).toContain('Apply filters')
  expect(html).toContain('Loading member activity…')
  expect(html).not.toContain('No member activity has been recorded yet.')
})

it('sends bounded search, type, date, and cursor parameters to the API', async () => {
  hook.states[9] = { query: 'Name 123', type: 'leave', from: '2026-10-01', to: '2026-10-31' }
  transport.mockResolvedValue({ events: [], next_cursor: null })
  render()
  await Promise.resolve()
  const requestUrl = transport.mock.calls[0][0] as string
  const params = new URLSearchParams(requestUrl.split('?')[1])
  expect(params.get('limit')).toBe('50')
  expect(params.get('q')).toBe('Name 123')
  expect(params.get('type')).toBe('leave')
  expect(params.get('from')).toBe('2026-10-01')
  expect(params.get('to')).toBe('2026-10-31')
  expect(params.has('before')).toBe(false)
})

it('clears protected history when access is denied', async () => {
  hook.states[0] = [fixture]
  transport.mockRejectedValue(new ApiError('No access', 403))
  render()
  await Promise.resolve()
  await Promise.resolve()
  expect(hook.states[0]).toEqual([])
  expect(hook.states[7]).toContain('Your staff access has changed.')
})

it('ignores a stale response after a newer filter read starts', async () => {
  let rejectOld!: (error: unknown) => void
  let resolveNew!: (value: unknown) => void
  transport
    .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject }))
    .mockImplementationOnce(() => new Promise(resolve => { resolveNew = resolve }))
  render()
  hook.states[9] = { query: 'new name', type: 'all', from: '', to: '' }
  render()
  resolveNew({ events: [{ ...fixture, id: 'new-event', display_name: 'New Result' }], next_cursor: null })
  await Promise.resolve()
  await Promise.resolve()
  rejectOld(new ApiError('Old request denied', 403))
  await Promise.resolve()
  await Promise.resolve()
  expect(hook.states[0]).toEqual([{ ...fixture, id: 'new-event', display_name: 'New Result' }])
  expect(hook.states[7]).toBe('')
})

it('shows kick and ban reasons and moderators in the compact history card', () => {
  hook.states[0] = [
    { ...fixture, id: 'kick-1', event_type: 'kick', reason: 'Spam <script>', moderator_id: '987654321', moderator_name: '<b>Moderator & Name</b>' },
    { ...fixture, id: 'ban-1', event_type: 'ban', reason: null, moderator_id: null },
  ]
  const html = render()
  expect(html).toContain('Kicked')
  expect(html).toContain('Banned')
  expect(html).toContain('title="987654321">&lt;b&gt;Moderator &amp; Name&lt;/b&gt;</span>')
  expect(html.replace(/<[^>]+>/g, '')).not.toContain('987654321')
  expect(html).toContain('an unknown moderator</span> · “No reason given”')
})

it('does not display archived raw-ID identity fallbacks', () => {
  hook.states[0] = [{ ...fixture, display_name: fixture.user_id, username: fixture.user_id,
    event_type: 'kick', moderator_id: '987654321', moderator_name: '987654321' }]
  const visible = render().replace(/<[^>]+>/g, '')
  expect(visible).toContain('Unknown member')
  expect(visible).toContain('an unknown moderator')
  expect(visible).not.toContain(fixture.user_id)
  expect(visible).not.toContain('987654321')
})
