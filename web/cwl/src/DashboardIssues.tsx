import { useEffect, useState } from 'react'
import { api, ApiError } from './api'
import type { MemberOption } from './MemberPicker'
import DiscordIdentity from './DiscordIdentity'
import './DashboardIssues.css'

export type Issue = { id: string; at: number; member: string | null; kind: string; status: number; action: string; method: string }
type History = { items: Issue[]; members?: Record<string, MemberOption>; profiles_available?: boolean }
export const issueLabels: Record<string, string> = {
  server_error: 'Server error', service_unavailable: 'Service unavailable',
  action_rejected: 'Action rejected', browser_error: 'Browser error',
  unhandled_promise: 'Browser operation failed', network_error: 'Connection problem',
}
export function matchesIssue(item: Issue, members: Record<string, MemberOption>, search: string, kind: string) {
  const profile = members[item.member || '']
  const text = [item.id, item.member, profile?.display_name, profile?.username, issueLabels[item.kind], item.action].join(' ').toLocaleLowerCase()
  return (!kind || item.kind === kind) && text.includes(search.trim().toLocaleLowerCase())
}

export default function DashboardIssues() {
  const [history, setHistory] = useState<History>({ items: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('')
  const [limit, setLimit] = useState(25)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    api<History>('/issues').then(data => { if (active) setHistory(data) })
      .catch(err => {
        if (!active) return
        if (err instanceof ApiError && [401, 403].includes(err.status)) setHistory({ items: [] })
        setError(err.message)
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])
  const members = history.members || {}
  const matching = history.items.filter(item => matchesIssue(item, members, search, kind))
  return <section className="dashboard-issues" aria-labelledby="issues-title">
    <p className="eyebrow">Owners only</p>
    <h1 id="issues-title">Dashboard issues</h1>
    <p className="issues-intro">See what failed and who was affected. Newest reports first.</p>
    <div className="issues-toolbar">
      <label>Find an issue<input type="search" placeholder="Name, Discord ID or reference" value={search} onChange={event => { setSearch(event.target.value); setLimit(25) }} /></label>
      <label>Issue type<select value={kind} onChange={event => { setKind(event.target.value); setLimit(25) }}>
        <option value="">All issues</option>
        {Object.entries(issueLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <button type="button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>{loading ? 'Checking…' : 'Refresh'}</button>
    </div>
    {error && <p className="notice error" role="alert">{error}{history.items.length > 0 && ' Showing previously loaded reports.'}</p>}
    {history.profiles_available === false && <p className="issues-hint" role="status">Discord profiles could not load. Saved user IDs are shown; refresh to try again.</p>}
    <p className="issues-count" role="status">{loading && !history.items.length ? 'Loading reports…' : `${matching.length} ${matching.length === 1 ? 'report' : 'reports'} · Last 30 days`}</p>
    {!loading && !error && !matching.length && <p>{search || kind ? 'No matching issues. Try another name or issue type.' : 'No recorded issues in the current history.'}</p>}
    <div className="issues-list" aria-busy={loading}>
      {matching.slice(0, limit).map(item => <article className="issue-row" key={item.id}>
        <div className="issue-summary">
          <h2><span className={`issue-dot ${item.kind === 'action_rejected' ? 'issue-dot-warning' : ''}`} aria-hidden="true" />{issueLabels[item.kind] || 'Dashboard issue'}</h2>
          <time dateTime={new Date(item.at * 1000).toISOString()}>{new Date(item.at * 1000).toLocaleString()}</time>
          <span className="issue-reference">Reference <code>{item.id}</code></span>
        </div>
        <div className="issue-member">
          <span className="issues-hint">Affected user</span>
          {item.member ? <DiscordIdentity userId={item.member} resolvedMember={members[item.member] || null} />
            : <p className="issues-unsigned">Not signed in <small>No Discord identity was recorded.</small></p>}
          {item.member && !/^\d{15,22}$/.test(item.member) && <small>Recorded ID: {item.member}</small>}
        </div>
        <details className="issue-details"><summary>Technical details</summary>
          <dl><dt>Request</dt><dd><code>{item.method} {item.action}</code></dd>
            <dt>Response</dt><dd>{item.status ? `HTTP ${item.status}` : 'Browser report · not independently verified'}</dd></dl>
          {item.kind === 'action_rejected' && <p>A permission or input check may have rejected this action.</p>}
        </details>
      </article>)}
    </div>
    {matching.length > limit && <button className="issues-more" type="button" onClick={() => setLimit(value => value + 25)}>Show more · {matching.length - limit} remaining</button>}
    <details className="issues-history"><summary>About this history</summary>
      <p>Up to 500 reports from the last 30 days. Rejected actions may be permission or input problems. Successful signups remain in signup history.</p>
      <p>Repeated browser reports are limited to one per member per minute. Offline browsers cannot send reports. Storage outages appear in service logs. This page does not send Discord alerts.</p>
    </details>
  </section>
}
