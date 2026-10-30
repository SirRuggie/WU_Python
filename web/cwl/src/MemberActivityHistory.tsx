import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import './MemberActivityHistory.css'
import { eventTypes } from './moderationSettingsModel'

type MemberEvent = {
  id: string
  user_id: string
  event_type: 'join' | 'leave' | 'kick' | 'ban'
  display_name?: string | null
  username?: string | null
  avatar_url?: string | null
  occurred_at: string
  joined_at?: string | null
  reason?: string | null
  moderator_id?: string | null
  moderator_name?: string | null
  delivery_status?: string | null
}
type Response = { events: MemberEvent[]; next_cursor: string | null }
type EventType = 'all' | 'join' | 'leave' | 'kick' | 'ban'
type Filters = { query: string; type: EventType; from: string; to: string }

const deliveryLabels: Record<string, string> = {
  queued: 'Delivery queued',
  sending: 'Delivery in progress',
  uncertain: 'Delivery uncertain',
  skipped: 'Delivery skipped while disabled',
}

function MemberAvatar({ name, url }: { name: string; url?: string | null }) {
  const [failed, setFailed] = useState(false)
  const safeUrl = url?.startsWith('/api/cwl/manage/member-events/') ? url : null

  if (safeUrl && !failed) {
    return (
      <img
        src={safeUrl}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
      />
    )
  }

  return (
    <span className="member-activity-avatar" aria-hidden="true">
      {Array.from(name)[0]?.toUpperCase() || '?'}
    </span>
  )
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function MemberActivityHistory({ active = true }: { active?: boolean }) {
  const [rows, setRows] = useState<MemberEvent[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [type, setType] = useState<EventType>('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadedAt, setLoadedAt] = useState('')
  const [filters, setFilters] = useState<Filters>({
    query: '',
    type: 'all',
    from: '',
    to: '',
  })
  const request = useRef(0)

  const load = useCallback(
    async (pageCursor: string | null, replace = true) => {
      const id = ++request.current
      setLoading(true)
      setError('')
      const params = new URLSearchParams({ limit: '50' })
      if (filters.query) params.set('q', filters.query)
      if (filters.type !== 'all') params.set('type', filters.type)
      if (filters.from) params.set('from', filters.from)
      if (filters.to) params.set('to', filters.to)
      if (pageCursor) params.set('before', pageCursor)

      try {
        const result = await api<Response>(`/manage/member-events?${params}`)
        if (request.current !== id) return
        setRows(current => (replace ? result.events : [...current, ...result.events]))
        setNextCursor(result.next_cursor || null)
        setLoadedAt(new Date().toISOString())
      } catch (cause) {
        if (request.current !== id) return
        if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
          setRows([])
          setNextCursor(null)
          setError('Your staff access has changed. Sign in again or ask an administrator to restore access.')
        } else {
          setError(cause instanceof Error ? cause.message : 'Could not load member activity. Try again.')
        }
      } finally {
        if (request.current === id) setLoading(false)
      }
    },
    [filters],
  )

  useEffect(() => {
    if (!active) {
      request.current += 1
      setLoading(false)
      return
    }
    void load(null)
    return () => {
      request.current += 1
    }
  }, [active, load])

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    request.current += 1
    setFilters({ query: search.trim(), type, from, to })
    setRows([])
  }

  const clearFilters = () => {
    request.current += 1
    setSearch('')
    setType('all')
    setFrom('')
    setTo('')
    setFilters({ query: '', type: 'all', from: '', to: '' })
    setRows([])
  }

  const showNext = () => {
    if (nextCursor) void load(nextCursor, false)
  }
  const noMatches = !loading && !error && rows.length === 0

  return (
    <section className="member-activity" aria-labelledby="member-activity-title">
      <header className="member-activity-heading">
        <div>
          <h2 id="member-activity-title">Activity history</h2>
          <p>Recent joins, leaves, kicks and bans. A kick or ban can also create a separate leave event.</p>
        </div>
        <button type="button" onClick={() => void load(null)} disabled={loading}>
          Refresh
        </button>
      </header>

      <form className="member-activity-filters" onSubmit={applyFilters}>
        <label className="member-activity-search">
          Search name or Discord ID
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Name or Discord ID"
          />
        </label>
        <label>
          Activity
          <select value={type} onChange={event => setType(event.target.value as EventType)}>
            <option value="all">All activity</option>
            <option value="join">Joins</option>
            <option value="leave">Leaves</option>
            <option value="kick">Kicks</option>
            <option value="ban">Bans</option>
          </select>
        </label>
        <details className="member-activity-date-range">
          <summary>Date range</summary>
          <div className="member-activity-date-fields">
            <label>
              From (UTC)
              <input type="date" value={from} onChange={event => setFrom(event.target.value)} />
            </label>
            <label>
              To (UTC)
              <input type="date" value={to} onChange={event => setTo(event.target.value)} />
            </label>
            <small className="member-activity-date-help">
              Dates use UTC. Event times below use your local timezone.
            </small>
          </div>
        </details>
        <button type="submit">Apply filters</button>
      </form>

      {error && (
        <div className="member-activity-error" role="alert">
          {error}
          <button type="button" disabled={loading} onClick={() => void load(null)}>
            Try again
          </button>
        </div>
      )}
      {error && rows.length > 0 && (
        <p className="member-activity-loaded">Showing the last loaded activity.</p>
      )}
      {loadedAt && !error && (
        <p className="member-activity-loaded">
          Updated{' '}
          <time dateTime={loadedAt}>
            {new Date(loadedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          </time>
        </p>
      )}
      {loading && (
        <p role="status" className="member-activity-status">
          {rows.length ? 'Updating activity…' : 'Loading member activity…'}
        </p>
      )}
      {noMatches && (
        <div className="member-activity-empty">
          <p>
            {filters.query || filters.type !== 'all' || filters.from || filters.to
              ? 'No activity matches these filters.'
              : 'No member activity has been recorded yet.'}
          </p>
          {(filters.query || filters.type !== 'all' || filters.from || filters.to) && (
            <button type="button" onClick={clearFilters}>Clear filters</button>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <>
          <ul className="member-activity-list" aria-label="Member join and leave history">
            {rows.map(item => {
              const identity = (value?: string | null) => value?.trim() !== item.user_id ? value?.trim() : ''
              const username = identity(item.username)
              const name = identity(item.display_name) || username || 'Unknown member'
              const moderatorName = item.moderator_name?.trim() !== item.moderator_id ? item.moderator_name?.trim() : ''
              const eventLabel = { join: 'Joined', leave: 'Left', kick: 'Kicked', ban: 'Banned' }[item.event_type]
              const eventIcon = eventTypes.find(event => event.key === item.event_type)?.icon || '●'
              const isModeration = item.event_type === 'kick' || item.event_type === 'ban'
              const deliveryText = item.delivery_status
                ? deliveryLabels[item.delivery_status] || ''
                : ''

              return (
                <li
                  key={item.id}
                  className={`member-activity-row is-${item.event_type}`}
                >
                  <div className="member-activity-identity">
                    <MemberAvatar name={name} url={item.avatar_url} />
                    <div>
                      <strong title={item.user_id}>{name}</strong>
                      {username && <small>@{username}</small>}
                    </div>
                  </div>
                  <span className={`member-activity-kind ${item.event_type}`}>
                    <span aria-hidden="true">{eventIcon}</span>
                    {eventLabel}
                  </span>
                  {isModeration && (
                    <p className="member-activity-moderation">
                      by <span title={item.moderator_id || undefined}>{moderatorName || 'an unknown moderator'}</span>
                      {' · '}“{item.reason?.trim() || 'No reason given'}”
                    </p>
                  )}
                  <div className="member-activity-meta">
                    <time className="member-activity-date" dateTime={item.occurred_at}>
                      {formatDate(item.occurred_at)}
                    </time>
                    {deliveryText && (
                      <small
                        className={`member-activity-delivery ${item.delivery_status === 'uncertain' ? 'uncertain' : ''}`}
                      >
                        {deliveryText}
                      </small>
                    )}
                  </div>
                  <details className="member-activity-details">
                    <summary>Details</summary>
                    <p title={item.user_id}>Member: {name}</p>
                    {item.joined_at && <p>Member joined {formatDate(item.joined_at)}</p>}
                    {item.reason && <p>Reason: {item.reason}</p>}
                    {item.moderator_id && <p title={item.moderator_id}>Moderator: {moderatorName || 'Unknown moderator'}</p>}
                    {deliveryText && <p>{deliveryText}</p>}
                    {!item.joined_at && !item.reason && !item.moderator_id && !deliveryText && <p>No additional details recorded.</p>}
                  </details>
                </li>
              )
            })}
          </ul>
          {nextCursor && (
            <div className="member-activity-more">
              <button type="button" onClick={showNext} disabled={loading}>
                Load older activity
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
