import { readSnapshot, writeSnapshot } from './snapshotCache'
import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, type Account, type Pool, type Season, type Session, type Signup } from './api'
import { clanDeepLink, memberPlacementStatus, type MyAssignments } from './publication'
import { availableSelection, dashboardRows, filterDashboardRows, type AccountFilter } from './dashboard'
import TownHallIcon from './TownHallIcon'
import './DashboardHome.css'

type Snapshot = { season?: Season; accounts: Account[]; signups: Signup[]; assignments: MyAssignments; checkedAt: string; linkInstruction: string }
type Props = {
  session: Session; seasonId: string; seasons: Season[]; onSeasonChange: (id: string) => void;
  onNavigate: (view: 'todo' | 'saved' | 'signup' | 'assignments' | 'roster' | 'publication' | 'staff') => void;
  onStart: (pool: Pool, tags: string[], accounts: Account[], signups: Signup[]) => void;
}
function ClanBadge({ url, name }: { url?: string | null; name: string }) {
  const [failed, setFailed] = useState('')
  return url && failed !== url ? <img className="hub-clan-badge" src={url} alt={`${name} badge`} width={40} height={40} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(url)} /> : <span className="hub-clan-fallback" aria-hidden="true">🛡️</span>
}
export default function DashboardHome(props: Props) {
  const { session, seasonId, seasons, onSeasonChange, onNavigate, onStart } = props
  const cacheKey = `home:${session.user.id}:${seasonId}`
  const [data, setData] = useState<Snapshot | null>(() => readSnapshot<Snapshot>(cacheKey, (value): value is Snapshot => { const v = value as Snapshot; return !!v && Array.isArray(v.accounts) && Array.isArray(v.signups) && Array.isArray(v.assignments?.accounts) && typeof v.checkedAt === 'string' }))
  const [cached, setCached] = useState(!!data)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [paused, setPaused] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [filter, setFilter] = useState<AccountFilter>('all')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('th')
  const [page, setPage] = useState(0)
  const season = data ? data.season : seasons.find(item => String(item.id) === seasonId)
  useEffect(() => {
    let cancelled = false, inFlight = false
    const load = async () => {
      if (inFlight || cancelled || document.hidden) return
      inFlight = true; setRefreshing(true)
      try {
        const [accounts, signups, assignments, currentSeasons] = await Promise.all([
          api<{ accounts: Account[]; link_instruction: string }>('/dashboard/accounts'),
          seasonId ? api<{ signups: Signup[] }>(`/seasons/${encodeURIComponent(seasonId)}/signups`) : Promise.resolve({ signups: [] }),
          seasonId ? api<MyAssignments>(`/seasons/${encodeURIComponent(seasonId)}/my-assignments`) : Promise.resolve({ accounts: [], published: null, visibility: 'current' as const, draft_changed: false }),
          api<{ seasons: Season[] }>('/seasons'),
        ])
        if (!cancelled) {
          const snapshot: Snapshot = { season: currentSeasons.seasons.find(item => String(item.id) === seasonId), accounts: accounts.accounts, signups: signups.signups, assignments, checkedAt: new Date().toISOString(), linkInstruction: accounts.link_instruction }
          setData(snapshot); writeSnapshot(cacheKey, snapshot); setCached(false)
          setSelected(current => availableSelection(current, dashboardRows(accounts.accounts, signups.signups, assignments.accounts)))
          setError('')
        }
      } catch (cause) { if (!cancelled) { if (cause instanceof ApiError && [401,403].includes(cause.status)) { setData(null); setCached(false) }; setError(cause instanceof Error ? cause.message : 'Could not refresh your dashboard.') } }
      finally { inFlight = false; if (!cancelled) setRefreshing(false) }
    }
    void load()
    const tick = () => { if (!paused) void load() }
    const timer = window.setInterval(tick, 30000)
    document.addEventListener('visibilitychange', tick)
    window.addEventListener('online', tick)
    return () => { cancelled = true; clearInterval(timer); document.removeEventListener('visibilitychange', tick); window.removeEventListener('online', tick) }
  }, [seasonId, refreshKey, paused])
  const rows = useMemo(() => dashboardRows(data?.accounts || [], data?.signups || [], data?.assignments.accounts || []), [data])
  const visible = useMemo(() => filterDashboardRows(rows, filter, search, sort), [rows, filter, search, sort])
  const unsigned = rows.filter(row => !row.signup).length
  const assigned = data?.assignments.accounts.filter(item => item.assigned_clan_tag).length || 0
  const waiting = (data?.signups.length || 0) - assigned
  const lastPage = Math.max(0, Math.ceil(visible.length / 12) - 1)
  const currentPage = Math.min(page, lastPage)
  const pageRows = visible.slice(currentPage * 12, (currentPage + 1) * 12)
  useEffect(() => { setPage(0) }, [filter, search, sort])
  const groups = new Map<string, typeof rows>()
  for (const row of pageRows) { const key = row.current_clan_tag || 'none'; groups.set(key, [...(groups.get(key) || []), row]) }
  const canSignup = !cached && !!season?.signup_open && season.status !== 'archived'
  const selectVisible = () => setSelected(current => [...new Set([...current, ...visible.filter(row => !row.signup).map(row => row.tag)])])
  return <div className="dashboard-home">
    <div className="page-head"><div><p className="eyebrow">Your Warriors United home</p><h1>Hey, {session.user.display_name || session.user.username} <span aria-hidden="true">👋</span></h1><p>Your accounts, your clans, and what to do next.</p></div><label className="season-choice">CWL season<select value={seasonId} onChange={event => onSeasonChange(event.target.value)}><option value="">Select a season</option>{seasons.map(item => <option key={item.id} value={String(item.id)}>{item.label}</option>)}</select></label></div>
    <div className="hub-sync"><span role="status"><span className={`status-dot ${!error && data ? 'active' : ''}`} />{cached ? (error ? 'Showing saved data · refresh failed' : 'Showing saved data · checking for updates…') : refreshing ? 'Refreshing…' : error ? 'Refresh needs attention' : data ? `Updated ${new Date(data.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Loading your accounts…'}</span><div><small>{paused ? 'Auto-refresh paused' : 'Auto-refresh every 30 seconds'}</small><button onClick={() => setPaused(value => !value)} aria-pressed={paused}>{paused ? 'Resume' : 'Pause'}</button><button disabled={refreshing} onClick={() => setRefreshKey(value => value + 1)} aria-label="Refresh dashboard">↻ Refresh</button></div></div>
    {error && <div className="notice error" role="alert"><div>{error}{data && <small>Showing your last successful update. Saved signups have not been removed.</small>}</div><button onClick={() => setRefreshKey(value => value + 1)}>Retry</button></div>}
    <section className="hub-next" aria-labelledby="hub-next-title"><div className="hub-next-symbol" aria-hidden="true">⚔️</div><div><p className="eyebrow">CWL · {season?.label || 'Season coming soon'}</p><h2 id="hub-next-title">{!data ? 'Getting your next steps ready' : !season ? 'Your next CWL starts here' : !rows.length ? 'Link your accounts to get started' : !canSignup ? 'Check your clan assignments' : unsigned ? 'Choose accounts for CWL' : 'Your accounts are signed up'}</h2><p>{cached ? 'Showing saved accounts. Checking signup availability…' : !season ? 'Staff will open a season here when signups are ready.' : !rows.length ? (data?.linkInstruction || 'Link your Clash accounts in Discord, then refresh here.') : canSignup && unsigned > 0 ? 'Select accounts, choose Main or Lazy, then review your signup.' : canSignup ? 'Your signups are saved. Open My assignments to see your clans.' : 'Signups are closed. Your saved accounts and clan assignments are still available.'}</p></div><button className="primary" onClick={() => onNavigate(canSignup && unsigned > 0 ? 'signup' : 'assignments')}>{canSignup && unsigned > 0 ? 'Go to signups →' : 'My assignments →'}</button></section>
    <section className="todo-home-link"><span aria-hidden="true">✅</span><div><h2>Your tasks</h2><p>War and CWL attacks, raids, and Clan Games across your linked accounts.</p></div><button onClick={() => onNavigate('todo')}>Open To do →</button></section>
    <div className="hub-stats" aria-label="Account overview">
      {([{ filter: 'all', icon: '🏰', label: 'Linked accounts', value: rows.length }, { filter: 'unsigned', icon: '✍️', label: 'Not signed up', value: unsigned }, { filter: 'waiting', icon: '⏳', label: 'Waiting for a clan', value: Math.max(0, waiting) }, { filter: 'assigned', icon: '🛡️', label: 'Assigned accounts', value: assigned }] as const).map(item => <button key={item.filter} aria-pressed={filter === item.filter} onClick={() => setFilter(item.filter)}><span aria-hidden="true">{item.icon}</span><strong>{data ? item.value : '—'}</strong><small>{item.label}</small></button>)}
    </div>
    <div className="hub-section-heading"><div><h2>My accounts</h2><p>Select accounts to sign up. Signed-up accounts show their assigned clan.</p></div><button onClick={() => onNavigate('assignments')}>My assignments ↗</button></div>
    <div className="hub-toolbar"><label>Find an account or clan<input type="search" placeholder="Name, player tag or clan…" value={search} onChange={event => setSearch(event.target.value)} /></label><label>Show<select value={filter} onChange={event => setFilter(event.target.value as AccountFilter)}><option value="all">All accounts</option><option value="unsigned">Not signed up</option><option value="waiting">Waiting for a clan</option><option value="assigned">Assigned</option></select></label><label>Sort<select value={sort} onChange={event => setSort(event.target.value)}><option value="th">Town Hall · highest first</option><option value="name">Account name · A–Z</option></select></label></div>
    {data && <><div className="hub-selection"><span>{selected.length} selected · {visible.length} matching accounts</span><div><button disabled={!canSignup || !visible.some(row => !row.signup)} onClick={selectVisible}>Select accounts not signed up</button><button disabled={!selected.length} onClick={() => setSelected([])}>Clear</button></div></div>
      {!rows.length ? <div className="card empty"><h3>🔗 Link your first account</h3><p>{data.linkInstruction || 'Use ClashKing’s /link command in Discord, then refresh here.'}</p><button onClick={() => setRefreshKey(value => value + 1)}>Check linked accounts</button></div> : !visible.length ? <div className="card empty"><h3>No accounts match</h3><p>Try another name or choose All accounts.</p><button onClick={() => { setSearch(''); setFilter('all') }}>Show all accounts</button></div> : <div className="hub-clans">{[...groups.entries()].map(([key, members]) => <section className="hub-clan" key={key}><header><ClanBadge url={members[0].current_clan_badge_url} name={members[0].current_clan_name || 'No current clan'} /><div><h3>{members[0].current_clan_name || 'No current clan'}</h3><small>Current clan{key !== 'none' ? ` · ${key}` : ''}</small></div>{key !== 'none' && <a className="hub-clan-link" href={clanDeepLink(key)} target="_blank" rel="noopener noreferrer">Open Clan ↗</a>}</header><div>{members.map(row => <article className={`hub-account ${selected.includes(row.tag) ? 'is-selected' : ''}`} key={row.tag}><label className="hub-account-pick"><input type="checkbox" aria-label={`Select ${row.name}`} disabled={!canSignup || !!row.signup} checked={selected.includes(row.tag)} onChange={event => setSelected(current => event.target.checked ? [...new Set([...current, row.tag])] : current.filter(tag => tag !== row.tag))} /><TownHallIcon level={row.town_hall} /><span><strong>{row.name}</strong><small>{row.tag}</small></span></label><div className="hub-account-status"><span className={`hub-state ${row.signup ? 'saved' : ''}`}>{row.signup ? `✓ ${row.signup.pool === 'main' ? 'Main' : 'Lazy'} CWL · Signed Up` : 'Not signed up'}</span>{row.signup && <small>{row.assignment?.assigned_clan_tag ? `🛡️ ${row.assignment.assigned_clan_name || row.assignment.assigned_clan_tag}` : '⏳ Waiting for a clan'}{row.assignment?.assigned_clan_tag && data.assignments && memberPlacementStatus(data.assignments) === 'provisional' ? ' · May change' : ''}</small>}</div>{row.signup && <button className="hub-account-action" onClick={() => onNavigate(row.assignment?.assigned_clan_tag ? 'assignments' : 'saved')}>{row.assignment?.assigned_clan_tag ? 'View clan' : 'Manage signup'} →</button>}</article>)}</div></section>)}</div>}
      {lastPage > 0 && <nav className="hub-pagination" aria-label="Account pages"><button disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>← Previous</button><span>Page {currentPage + 1} of {lastPage + 1}</span><button disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}>Next →</button></nav>}
      {selected.length > 0 && <div className="hub-selected-bar"><div><strong>{selected.length} account{selected.length === 1 ? '' : 's'} selected</strong><small>Choose a pool, then review. Nothing is submitted yet.</small></div><button className="primary" disabled={!canSignup} onClick={() => onStart('main', selected, data.accounts, data.signups)}>⚔️ Main CWL →</button><button className="primary" disabled={!canSignup} onClick={() => onStart('lazy', selected, data.accounts, data.signups)}>🌙 Lazy CWL →</button></div>}
    </>}
    <div className="hub-bottom"><details className="hub-help"><summary>🔗 Missing an account?</summary><p>{data?.linkInstruction || 'Use ClashKing’s /link command in Discord, then refresh this page.'}</p><p>Already signed-up accounts can be moved or withdrawn in My signups.</p><button onClick={() => onNavigate('saved')}>Open My signups →</button></details>{session.can_edit && <section className="hub-staff"><h3>🧭 Staff tools</h3><div><button onClick={() => onNavigate('roster')}>Build roster →</button><button onClick={() => onNavigate('publication')}>Publish roster →</button><button onClick={() => onNavigate('staff')}>Seasons & clans →</button></div></section>}</div>
  </div>
}
