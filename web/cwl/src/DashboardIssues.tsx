import { useEffect, useState } from 'react'
import { api } from './api'

type Issue = { id: string; at: number; member: string | null; kind: string; status: number; action: string; method: string }
const labels: Record<string, string> = {
  server_error: 'Server error', service_unavailable: 'Service unavailable',
  action_rejected: 'Action could not be completed', browser_error: 'Browser error',
  unhandled_promise: 'Browser operation failed', network_error: 'Connection problem',
}

export default function DashboardIssues() {
  const [items, setItems] = useState<Issue[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [search, setSearch] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    api<{items: Issue[]}>('/issues').then(data => { if (active) setItems(data.items) })
      .catch(err => { if (active) { setItems([]); setError(err.message) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])
  const matching = items.filter(item => `${item.id} ${item.member || ''}`.includes(search.trim()))
  return <section aria-labelledby="issues-title">
    <p className="eyebrow">Owners only</p><h1 id="issues-title">Dashboard issues</h1>
    <p>Recent failed actions and browser reports. A rejected action can be a permission or input problem, not a software fault.</p>
    <div className="card">
      <label>Find a reference or Discord user ID<input value={search} onChange={event => setSearch(event.target.value)} /></label>
      <button disabled={loading} onClick={() => setRefresh(value => value + 1)}>{loading ? 'Checking…' : 'Refresh issues'}</button>
    </div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!loading && !error && !matching.length && <p role="status">{search ? 'No matching issues.' : 'No recorded issues in the current history.'}</p>}
    {!loading && !error && matching.map(item => <article className="card" key={item.id}>
      <h2>{labels[item.kind] || 'Dashboard issue'}</h2>
      <p><time dateTime={new Date(item.at * 1000).toISOString()}>{new Date(item.at * 1000).toLocaleString()}</time></p>
      <p>Reference: <strong>{item.id}</strong> · Discord user ID: {item.member || 'Not signed in'}</p>
      <details><summary>Technical details</summary>
        <p style={{overflowWrap: 'anywhere'}}>{item.method} {item.action}</p>
        <p>{item.status ? `HTTP status: ${item.status}` : 'Reported by the browser; not independently verified.'}</p>
      </details>
    </article>)}
    <details><summary>What this history includes</summary>
      <p>Up to 500 recent reports, showing the last 30 days. Repeated browser reports are limited to one per member per minute. Successful signups remain in signup history.</p>
      <p>Offline browsers cannot send reports. Login failures may have no member ID. Storage outages are recorded in service logs. This page does not send Discord alerts.</p>
    </details>
  </section>
}
