import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { trackingIssues, trackingStatusLabel, trackingSummary, type ClanTracking } from './strikeTracking'

const when = (value?: string | null) => value ? new Date(value).toLocaleString() : 'Not yet'
const message = (error: unknown) => error instanceof Error ? error.message : 'Could not load tracking status.'

export default function StrikeTrackingStatus({ canRetry }: { canRetry: boolean }) {
  const [clans, setClans] = useState<ClanTracking[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retryError, setRetryError] = useState('')
  const [busyClan, setBusyClan] = useState('')
  const request = useRef(0)
  const mounted = useRef(true)

  const load = async () => {
    const current = ++request.current
    try {
      const data = await api<{ clans: ClanTracking[] }>('/strikes/tracking')
      if (mounted.current && current === request.current) { setClans(data.clans || []); setError('') }
    } catch (err) {
      if (mounted.current && current === request.current) setError(message(err))
    } finally {
      if (mounted.current && current === request.current) setLoading(false)
    }
  }
  useEffect(() => {
    mounted.current = true
    void load()
    const timer = window.setInterval(() => void load(), 30_000)
    return () => { mounted.current = false; request.current++; window.clearInterval(timer) }
  }, [])
  const retry = async (clanTag: string) => {
    setBusyClan(clanTag); setRetryError('')
    try {
      await api('/strikes/tracking/retry', 'POST', { clan_tag: clanTag })
      if (!mounted.current) return
      setClans(current => current.map(item => item.clan_tag === clanTag ? { ...item, retry_pending: true } : item))
      await load()
    } catch (err) { if (mounted.current) setRetryError(message(err)) }
    finally { if (mounted.current) setBusyClan('') }
  }
  const summary = trackingSummary(clans)
  const tone = error ? 'warning' : summary.tone
  return <details className={`card strikes-tracking ${tone}`}>
    <summary><span>Tracking</span><strong>{loading ? 'Checking…' : error ? 'Status unavailable' : summary.label}</strong></summary>
    <div className="strikes-tracking-body">
      {error && <div className="notice error" role="alert">{error}<button type="button" onClick={() => void load()}>Check again</button></div>}
      {retryError && <div className="notice error" role="alert">{retryError}</div>}
      {!loading && !error && clans.length === 0 && <p>No clan checks yet.</p>}
      {!error && clans.map(item => <div className="strikes-tracking-clan" key={item.clan_tag}>
        <div><strong>{item.clan_name || item.clan_tag}</strong><span className={`strikes-tracking-state ${item.status}`}>{trackingStatusLabel(item.status)}</span></div>
        <small>Checked {when(item.last_checked_at)} · Last successful {when(item.last_success_at)} · Latest war {when(item.latest_recorded_war_at)}</small>
        {(item.deferred_accounts || item.skipped_wars) ? <small>{trackingIssues(item)}</small> : null}
        {item.error && <small className="strikes-tracking-error">{item.error}</small>}
        {canRetry && item.status !== 'healthy' && <button type="button" disabled={!!busyClan || item.retry_pending} onClick={() => void retry(item.clan_tag)}>{item.retry_pending ? 'Retry queued' : busyClan === item.clan_tag ? 'Queuing…' : 'Retry'}</button>}
      </div>)}
    </div>
  </details>
}
