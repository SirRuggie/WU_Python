import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
export type WarSide = {badge_url?: string | null; tag: string; name: string; stars: number | null; destruction: number | null; attacks: number | null}
export type War = {my_accounts?: {tag: string; name: string; attacks_left: number | null; attacks_total: number | null}[]; state: string; clan?: WarSide; opponent?: WarSide; team_size?: number | null; attacks_total?: number | null; starts_at?: number | null; ends_at?: number | null}
export type Raid = {state: string; starts_at?: number | null; ends_at?: number | null; attacks?: number | null; districts?: number | null; loot?: number | null}
export type ClanActivity = {current_member?: boolean; accounts?: {tag: string; name: string}[]; tag: string; name: string; regular?: War; cwl?: War; raid?: Raid}
type Snapshot = {scope: string; checked_at: string; clans: ClanActivity[]; warnings: string[]}
export function useClanActivity(kind: 'war' | 'raid', scope: 'mine' | 'family') {
  const [data, setData] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => { setData(null) }, [scope, kind])
  useEffect(() => {
    let active = true, inflight = false
    const load = async () => {
      if (inflight || document.hidden) return
      inflight = true; setBusy(true)
      try {
        const next = await api<Snapshot>(`/clan-activity?kind=${kind}&scope=${scope}`)
        if (active) { setData(next); setError('') }
      } catch (cause) {
        if (active) {
          if (cause instanceof ApiError && [401,403].includes(cause.status)) setData(null)
          setError(cause instanceof Error ? cause.message : 'Clan activity could not be loaded.')
        }
      } finally { inflight = false; if (active) setBusy(false) }
    }
    void load()
    const timer = window.setInterval(load, 60000)
    document.addEventListener('visibilitychange', load)
    return () => { active = false; clearInterval(timer); document.removeEventListener('visibilitychange', load) }
  }, [kind, scope, revision])
  return {data: data?.scope === scope ? data : null, error, busy, refresh: () => setRevision(value => value + 1)}
}
