import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import {
  currentWarStateLabel,
  displayTrackingStatus,
  trackingIssues,
  trackingStatusLabel,
  trackingSummary,
  type ClanTracking,
  type TrackingResponse,
} from './strikeTracking'

const when = (value?: string | null) => {
  if (!value) return 'Not yet'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unavailable' : date.toLocaleString()
}
const message = (error: unknown) =>
  error instanceof Error ? error.message : 'Could not load tracking status.'

export default function StrikeTrackingStatus({
  canRetry,
}: {
  canRetry: boolean
}) {
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
      const data = await api<TrackingResponse>('/strikes/tracking')
      if (mounted.current && current === request.current) {
        setClans(data.clans || [])
        setError('')
      }
    } catch (cause) {
      if (mounted.current && current === request.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setClans([])
        setError(message(cause))
      }
    } finally {
      if (mounted.current && current === request.current) setLoading(false)
    }
  }

  useEffect(() => {
    mounted.current = true
    void load()
    const timer = window.setInterval(() => void load(), 30_000)
    return () => {
      mounted.current = false
      request.current++
      window.clearInterval(timer)
    }
  }, [])

  const retry = async (clanTag: string) => {
    setBusyClan(clanTag)
    setRetryError('')
    try {
      await api('/strikes/tracking/retry', 'POST', { clan_tag: clanTag })
      if (!mounted.current) return
      setClans((current) =>
        current.map((item) =>
          item.clan_tag === clanTag ? { ...item, retry_pending: true } : item,
        ),
      )
      await load()
    } catch (cause) {
      if (mounted.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setClans([])
        setRetryError(message(cause))
      }
    } finally {
      if (mounted.current) setBusyClan('')
    }
  }

  const summary = trackingSummary(clans)
  const tone = error ? 'warning' : summary.tone
  return (
    <details className={`card strikes-tracking ${tone}`}>
      <summary>
        <span>Tracking</span>
        <strong>
          {loading ? 'Checking…' : error ? 'Status unavailable' : summary.label}
        </strong>
      </summary>
      <div className="strikes-tracking-body">
        {error && (
          <div className="notice error" role="alert">
            {error}
            <button type="button" onClick={() => void load()}>
              Check again
            </button>
          </div>
        )}
        {retryError && (
          <div className="notice error" role="alert">
            {retryError}
          </div>
        )}
        {!loading && !error && clans.length === 0 && <p>No clan checks yet.</p>}
        {!error &&
          clans.map((item) => {
            const status = displayTrackingStatus(item)
            return (
              <div className="strikes-tracking-clan" key={item.clan_tag}>
                <div className="strikes-tracking-clan-heading">
                  <strong>{item.clan_name || item.clan_tag}</strong>
                  <span className={`strikes-tracking-state ${status}`}>
                    {trackingStatusLabel(status)}
                  </span>
                </div>
                <div className="strikes-tracking-facts">
                  <small>
                    Last war recorded{' '}
                    <strong>{when(item.latest_recorded_war_at)}</strong>
                  </small>
                  <small>
                    Current war{' '}
                    <strong>
                      {currentWarStateLabel(item.current_war_state)}
                    </strong>
                  </small>
                </div>
                <small>
                  Checked {when(item.last_checked_at)} · Last successful{' '}
                  {when(item.last_success_at)}
                </small>
                {item.deferred_accounts || item.skipped_wars ? (
                  <small>{trackingIssues(item)}</small>
                ) : null}
                {item.error && (
                  <small className="strikes-tracking-error">{item.error}</small>
                )}
                {canRetry && status !== 'healthy' && (
                  <button
                    type="button"
                    disabled={!!busyClan || item.retry_pending}
                    onClick={() => void retry(item.clan_tag)}
                  >
                    {item.retry_pending
                      ? 'Retry queued'
                      : busyClan === item.clan_tag
                        ? 'Queuing…'
                        : 'Retry'}
                  </button>
                )}
              </div>
            )
          })}
      </div>
    </details>
  )
}
