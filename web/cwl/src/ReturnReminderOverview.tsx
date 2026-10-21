import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { ManagementDocument, ManagementSection, ReturnStatus } from './serverManagement'

export function ReturnStatusSummary({ status }: { status: ReturnStatus }) {
  return <div className="return-status-grid"><article>
    <strong>{status.label}</strong><span>{status.players} saved players</span>
    {status.every_minutes && <span>Every {status.every_minutes} minutes</span>}
    <small>Last recorded send: {status.last_sent_at ? new Date(status.last_sent_at).toLocaleString() : 'None recorded'}</small>
    {status.expires_at && <small>Window ends: {new Date(status.expires_at).toLocaleString()}</small>}
  </article></div>
}

export default function ReturnReminderOverview({ onOpen }: { onOpen: (section: ManagementSection) => void }) {
  const [records, setRecords] = useState<ManagementSection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [loadedAt, setLoadedAt] = useState('')
  const request = useRef(0)
  const load = useCallback(async () => {
    const id = ++request.current
    setLoading(true); setError('')
    try {
      const result = await api<ManagementDocument>('/manage/return-reminders')
      if (id !== request.current) return
      setRecords(result.documents || []); setLoadedAt(new Date().toLocaleTimeString())
    } catch (cause) {
      if (id !== request.current) return
      if (cause instanceof ApiError && [401,403].includes(cause.status)) { setRecords([]); setLoadedAt('') }
      setError(cause instanceof Error ? cause.message : 'Could not load return reminders.')
    } finally { if (id === request.current) setLoading(false) }
  }, [])
  useEffect(() => { void load(); return () => { request.current++ } }, [load])
  const clans = records.filter(row => row.return_status)
  const visible = clans.filter(row => (filter === 'all' || row.return_status?.state === filter) && `${row.label} ${row.id}`.toLowerCase().includes(query.trim().toLowerCase()))
  return <section aria-label="Return reminder overview">
    <div className="section-heading"><button disabled={loading} onClick={() => void load()}>Refresh overview</button></div>
    <p className="small">Scheduled reflects saved settings. It does not confirm worker health or Discord delivery.{loadedAt && ` Loaded ${loadedAt}.`}</p>
    {error && <p className="notice error" role="alert">{error}{loadedAt && ' Showing the last loaded overview.'}<button disabled={loading} onClick={() => void load()}>Retry overview</button></p>}
    {loading && <p role="status">Loading return reminders…</p>}
    <div className="clan-category-filters" role="group" aria-label="Return reminder status">
      {([['all','All clans'],['scheduled','Scheduled'],['paused','Paused'],['idle','Not started'],['manual','Manual'],['not_saved','No list'],['expired','Window ended']] as const).map(([value,label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label} <span>{value === 'all' ? clans.length : clans.filter(row => row.return_status?.state === value).length}</span></button>)}
    </div>
    <label>Find a home clan<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Clan name or tag" /></label>
    <div className="return-status-grid">{visible.map(row => <article key={row.id}><strong>{row.label}</strong><span>{row.return_status!.label} · {row.return_status!.players} saved players</span><small>{row.return_status!.last_sent_at ? `Last recorded send ${new Date(row.return_status!.last_sent_at!).toLocaleString()}` : 'No send recorded'}</small><button onClick={() => onOpen(row)}>Manage return list</button></article>)}</div>
    {!loading && !error && !visible.length && <p>{clans.length ? 'No clans match these filters.' : 'No home clans are available yet.'}</p>}
    <details className="card"><summary>Channels, multiple-clan actions &amp; history</summary><div className="manage-section-choices">{records.filter(row => !row.return_status).map(row => <button key={row.id} onClick={() => onOpen(row)}>{row.label}</button>)}</div></details>
  </section>
}
