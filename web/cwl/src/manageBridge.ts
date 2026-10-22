import type { Pool } from './api'
export type ManageDelivery = { status: 'pending' | 'sending' | 'sent' | 'failed' | 'uncertain' | 'stale'; message_url?: string | null; error?: string | null; requested_at?: string | null; updated_at?: string | null; started_at?: string | null; sent_at?: string | null }
export type ManageButton = { label: string; url: string; emoji?: string | null }
export type ManagePool = { channel_id: string | null; title: string; body: string; media_url: string | null; buttons: ManageButton[]; role_ids: string[]; enabled: boolean; delivery: ManageDelivery | null; roster_url: string | null }
export type ManageBridge = { cycle: string | null; generation: string | null; worker_ready: boolean; pools: Record<Pool, ManagePool>; published_version: number | null }
const emptyPool = (): ManagePool => ({ channel_id: null, title: '', body: '', media_url: null, buttons: [], role_ids: [], enabled: false, delivery: null, roster_url: null })
export function normalizeManageBridge(value: ManageBridge): ManageBridge {
  return { ...value, pools: { main: value.pools?.main || emptyPool(), lazy: value.pools?.lazy || emptyPool() } }
}
export function canQueueAnnouncement(bridge: ManageBridge | null, pool: Pool, channelId: string, unsaved: boolean): boolean {
  if (!bridge?.cycle || !bridge.generation || !bridge.worker_ready || !bridge.published_version || unsaved) return false
  const entry = bridge.pools[pool]
  if (!entry.enabled || !entry.channel_id || entry.channel_id !== channelId) return false
  return !entry.delivery || entry.delivery.status === 'failed' || entry.delivery.status === 'stale'
}
export function shouldPollBridge(bridge: ManageBridge | null): boolean {
  return !!bridge && (['main', 'lazy'] as Pool[]).some(pool => ['pending', 'sending'].includes(bridge.pools[pool].delivery?.status || ''))
}
export function dashboardRosterUrl(origin: string, seasonId: string): string {
  const url = new URL('/assignments', origin)
  url.searchParams.set('season', seasonId)
  return url.toString()
}
