// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import RosterWorkspace from './RosterWorkspace'
import { DashboardPermissions } from './DashboardPermissions'
import type { RosterAccount, RosterSnapshot } from './roster'

const { api } = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('./api', async (original) => ({ ...(await original<object>()), api }))
vi.mock('./RosterHeader', () => ({ default: () => null }))
vi.mock('./SignupActivity', () => ({ default: () => null }))

const accounts = Array.from({ length: 51 }, (_, index) => ({
  tag: index === 50 ? '#SPECIAL' : `#PLAYER${index}`,
  user_id: String(index),
  player_name:
    index === 50
      ? 'Special account'
      : `Player ${String(index).padStart(2, '0')}`,
  pool: 'main',
  town_hall: 16,
  source_weight: 179000 - index,
  source_status: 'current',
  source_name: 'fixture',
  source_checked_at: null,
  source_modified_at: null,
  manual_weight: null,
  effective_weight: 179000 - index,
  assigned_clan_tag: null,
  kept: index === 0 || index === 3,
  prefer_crystal_1_or_lower: false,
})) as RosterAccount[]

it('hides All above 50, keeps quick picks in filtered order, and shows All at 50', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  HTMLElement.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  sessionStorage.clear()
  localStorage.clear()
  const snapshot = (count: number): RosterSnapshot => ({
    revision: 1,
    accounts: accounts.slice(0, count),
    clans: [],
    undo: null,
    metadata_updating: false,
  })
  api.mockImplementation(async (path: string) =>
    snapshot(path.includes('/seasons/2/') ? 50 : 51),
  )
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const render = (seasonId: string) =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <RosterWorkspace
          seasonId={seasonId}
          seasons={[]}
          onSeasonChange={() => {}}
        />
      </DashboardPermissions.Provider>,
    )
  const button = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>('button')].find(
      (item) => item.textContent?.trim() === label,
    )
  const search = async (value: string) => {
    const input = host.querySelector<HTMLInputElement>('input[type="search"]')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }
  try {
    await act(async () => render('1'))
    expect(host.textContent).toContain('51 matching')
    expect(button('All 51')).toBeUndefined()
    await act(async () => button('Select 15')!.click())
    const selected = [
      ...host.querySelectorAll<HTMLInputElement>(
        '.roster-player-select input:checked',
      ),
    ]
    expect(selected).toHaveLength(15)
    expect(host.textContent).toContain('15 selected')
    expect(
      host.querySelector<HTMLInputElement>(
        '[aria-label="Select Player 00 for bulk actions"]',
      )?.checked,
    ).toBe(false)
    expect(
      host.querySelector<HTMLInputElement>(
        '[aria-label="Select Player 03 for bulk actions"]',
      )?.checked,
    ).toBe(false)
    await search('Player')
    expect(host.textContent).toContain('50 matching · 15 selected')
    await act(async () => button('All 50')!.click())
    expect(host.textContent).toContain('50 selected')
    await search('Special')
    expect(host.textContent).toContain('1 matching · 50 selected')
    expect(host.textContent).toContain('50 hidden by filters')
    await act(async () =>
      host
        .querySelector<HTMLInputElement>(
          '[aria-label="Select Special account for bulk actions"]',
        )!
        .click(),
    )
    expect(host.textContent).toContain('50 is the most per action')
    expect(host.textContent).toContain('1 matching · 50 selected')
    await act(async () => button('Select 30')!.click())
    expect(host.textContent).toContain('Only 1 unlocked account matches')
    expect(host.textContent).toContain('1 matching · 1 selected')
    await act(async () => render('2'))
    expect(host.textContent).toContain('50 matching')
    expect(button('All 50')).toBeDefined()
  } finally {
    await act(async () => root.unmount())
    host.remove()
    api.mockReset()
    vi.unstubAllGlobals()
    sessionStorage.clear()
    localStorage.clear()
  }
})
