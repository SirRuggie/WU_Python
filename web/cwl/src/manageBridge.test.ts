import { describe, expect, it } from 'vitest'
import { canQueueAnnouncement, dashboardRosterUrl, normalizeManageBridge, shouldPollBridge, type ManageBridge } from './manageBridge'
const pool = { channel_id: '123', title: 'Roster', body: 'Read this', media_url: null, buttons: [], role_ids: [], enabled: true, delivery: null, roster_url: null }
const bridge: ManageBridge = { cycle: '2026-11', generation: 'rev-1', worker_ready: true, published_version: 2, pools: { main: pool, lazy: { ...pool, channel_id: '456' } } }
describe('Manage campaign bridge', () => {
  it('queues only explicit, saved, ready campaigns and allows known failure retry', () => {
    expect(canQueueAnnouncement(bridge, 'main', '123', false)).toBe(true)
    expect(canQueueAnnouncement(bridge, 'main', '456', false)).toBe(false)
    expect(canQueueAnnouncement(bridge, 'main', '123', true)).toBe(false)
    expect(canQueueAnnouncement({ ...bridge, worker_ready: false }, 'main', '123', false)).toBe(false)
    expect(canQueueAnnouncement({ ...bridge, pools: { ...bridge.pools, main: { ...pool, delivery: { status: 'failed' } } } }, 'main', '123', false)).toBe(true)
    expect(canQueueAnnouncement({ ...bridge, pools: { ...bridge.pools, main: { ...pool, delivery: { status: 'stale' } } } }, 'main', '123', false)).toBe(true)
    expect(canQueueAnnouncement({ ...bridge, pools: { ...bridge.pools, main: { ...pool, delivery: { status: 'sent' } } } }, 'main', '123', false)).toBe(false)
  })
  it('polls only queued or sending work', () => {
    expect(shouldPollBridge(bridge)).toBe(false)
    expect(shouldPollBridge({ ...bridge, pools: { ...bridge.pools, main: { ...pool, delivery: { status: 'pending' } } } })).toBe(true)
    expect(shouldPollBridge({ ...bridge, pools: { ...bridge.pools, main: { ...pool, delivery: { status: 'uncertain' } } } })).toBe(false)
  })
  it('normalizes unbound campaigns before a pool is selected', () => {
    const unbound = normalizeManageBridge({ ...bridge, cycle: null, generation: null, pools: {} as ManageBridge['pools'] })
    expect(unbound.pools.main.channel_id).toBeNull()
    expect(canQueueAnnouncement(unbound, 'main', '123', false)).toBe(false)
  })
  it('creates a direct assignment URL with a season selector', () => {
    expect(dashboardRosterUrl('https://cwl.example', '12')).toBe('https://cwl.example/assignments?season=12')
  })
})
