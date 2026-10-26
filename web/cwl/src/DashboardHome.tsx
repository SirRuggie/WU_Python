import { useJourneyState, useJourneyPosition } from './journeyState'
import { loadAccountDisplay, mergeAccountProgress, type AccountDisplay } from './accountDisplay'
import { weightText } from './roster'
import AccountLinkHelp from './AccountLinkHelp'
import DashboardIcon from './DashboardIcon'
import { readSnapshot, writeSnapshot } from './snapshotCache'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, type Account, type Pool, type Season, type Session, type Signup } from './api'
import { memberPlacementStatus, type MyAssignments } from './publication'
import { availableSelection, dashboardRows, filterDashboardRows, type AccountFilter } from './dashboard'
import TownHallIcon from './TownHallIcon'
import './DashboardHome.css'
import PlayerClanDetailsDialog from './PlayerClanDetailsDialog'
import MemberDetailActivity from './MemberDetailActivity'

type Snapshot = { season?: Season; accounts: Account[]; signups: Signup[]; assignments: MyAssignments; checkedAt: string; linkInstruction: string }
export function homeNextStep(complete: boolean, season: Season | undefined, accountCount: number, unsigned: number, issue: 'loading' | 'saved' | 'error' = 'loading') {
  if (!complete && issue === 'error') return { title: 'Could not check CWL status', detail: 'Refresh to confirm your latest signups and assignments. Any account details shown may be out of date.', destination: null }
  if (!complete && issue === 'saved') return { title: 'Checking saved CWL status', detail: 'Saved account details may be out of date. Checking signup availability…', destination: null }
  if (!complete) return { title: 'Checking your CWL status', detail: 'Account and signup details are still loading. Review the latest status below when the check finishes.', destination: null }
  if (!season) return { title: 'Your next CWL starts here', detail: 'Staff will open a season when signups are ready.', destination: null }
  if (!accountCount) return { title: 'Link your accounts to get started', detail: 'Link your Clash accounts in Discord, then refresh this page.', destination: 'help' as const }
  if (season.signup_open && season.status === 'draft' && unsigned) return { title: `${unsigned} account${unsigned === 1 ? '' : 's'} to sign up`, detail: 'Choose Main or Lazy for your accounts, then review before saving.', destination: 'signup' as const }
  if (season.signup_open && season.status === 'draft') return { title: 'Your accounts are signed up', detail: 'Your saved signups and clan assignments are ready to review.', destination: 'assignments' as const }
  return { title: 'Review your CWL status', detail: 'Signups are closed. Your saved accounts and clan assignments remain available.', destination: 'assignments' as const }
}
type Props = {
  session: Session; seasonId: string; seasons: Season[];
  onNavigate: (view: 'search' | 'wars' | 'events' | 'todo' | 'saved' | 'signup' | 'assignments' | 'roster' | 'publication' | 'staff') => void;
  onStart: (pool: Pool, tags: string[], accounts: Account[], signups: Signup[]) => void;
}
function ClanBadge({ url, name }: { url?: string | null; name: string }) {
  const [failed, setFailed] = useState('')
  return url && failed !== url ? <img className="hub-clan-badge" src={url} alt={`${name} badge`} width={40} height={40} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(url)} /> : <span className="hub-clan-fallback" aria-hidden="true"><DashboardIcon name="shield"/></span>
}
export default function DashboardHome(props: Props) {
  const { session, seasonId, seasons, onNavigate, onStart } = props
  const cacheKey = `home:${session.user.id}:${seasonId}`
  const [data, setData] = useState<Snapshot | null>(() => readSnapshot<Snapshot>(cacheKey, (value): value is Snapshot => { const v = value as Snapshot; return !!v && Array.isArray(v.accounts) && Array.isArray(v.signups) && Array.isArray(v.assignments?.accounts) && typeof v.checkedAt === 'string' }))
  const readGeneration = useRef(0)
  const [cached, setCached] = useState(!!data)
  const [partial, setPartial] = useState(false)
  const [detail, setDetail] = useState<{kind: 'player' | 'clan'; tag: string} | null>(null)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [paused, setPaused] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [filter, setFilter] = useJourneyState<AccountFilter>(`home:${session.user.id}:filter`, 'all')
  const [search, setSearch] = useJourneyState(`home:${session.user.id}:search`, '')
  const [sort, setSort] = useJourneyState(`home:${session.user.id}:sort`, 'th')
  const [page, setPage] = useJourneyState(`home:${session.user.id}:page`, 0)
  useJourneyPosition(`home:${session.user.id}`, !!data || !!error)
  const season = data ? data.season : seasons.find(item => String(item.id) === seasonId)
  useEffect(() => {
    const generation = ++readGeneration.current
    let cancelled = false, inFlight = false
    const load = async () => {
      if (inFlight || cancelled || generation !== readGeneration.current || document.hidden) return
      inFlight = true; setRefreshing(true)
      let accepting = true
      try {
        let progress: AccountDisplay | null = null
        let context: { signups: Signup[]; assignments: MyAssignments; season?: Season } | null = null
        const showProgress = () => {
          if (cancelled || generation !== readGeneration.current || !accepting || !context || !progress || (progress.total === null && progress.updating)) return
          const partial = progress
          const resolved = context
          setPartial(true)
          setData(previous => ({ ...resolved, accounts: mergeAccountProgress(previous?.accounts || [], partial), checkedAt: new Date().toISOString(), linkInstruction: partial.link_instruction }))
          // Partial results are view-only and never persisted as a complete snapshot.
        }
        const accountRead = loadAccountDisplay(snapshot => { progress = snapshot; showProgress() }, () => !cancelled && generation === readGeneration.current && accepting, refreshKey > 0)
        const contextRead = Promise.all([
          seasonId ? api<{ signups: Signup[] }>(`/seasons/${encodeURIComponent(seasonId)}/signups`) : Promise.resolve({ signups: [] }),
          seasonId ? api<MyAssignments>(`/seasons/${encodeURIComponent(seasonId)}/my-assignments`) : Promise.resolve({ accounts: [], published: null, visibility: 'current' as const, draft_changed: false }),
          api<{ seasons: Season[] }>('/seasons'),
        ]).then(([signups, assignments, currentSeasons]) => {
          context = { signups: signups.signups, assignments, season: currentSeasons.seasons.find(item => String(item.id) === seasonId) }
          showProgress()
          return context
        })
        const [accounts, resolved] = await Promise.all([accountRead, contextRead])
        if (!cancelled && generation === readGeneration.current) {
          const snapshot: Snapshot = { ...resolved, accounts: accounts.accounts, checkedAt: new Date().toISOString(), linkInstruction: accounts.link_instruction }
          setData(snapshot); writeSnapshot(cacheKey, snapshot); setCached(false); setPartial(false)
          setSelected(current => availableSelection(current, dashboardRows(accounts.accounts, resolved.signups, resolved.assignments.accounts)))
          setError('')
        }
      } catch (cause) { accepting = false; if (!cancelled && generation === readGeneration.current) { if (cause instanceof ApiError && [401,403].includes(cause.status)) { setData(null); setCached(false); setPartial(false); setDetail(null) }; setError(cause instanceof Error ? cause.message : 'Could not refresh your dashboard.') } }
      finally { accepting = false; inFlight = false; if (!cancelled) setRefreshing(false) }
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
  const detailPlayer = detail?.kind === 'player' ? rows.find(row => row.tag === detail.tag) : undefined
  const detailClanAccount = detail?.kind === 'clan' ? rows.find(row => row.current_clan_tag === detail.tag) : undefined
  const denyDetails = () => { readGeneration.current++; setSelected([]); setRefreshing(false); setDetail(null); setData(null); setCached(false); setPartial(false); setError('Your account access changed. Refresh or sign in again.') }
  const detailFreshness = error ? 'unavailable' : partial ? 'partial' : cached ? 'saved' : 'current'
  const unsigned = rows.filter(row => !row.signup).length
  const assigned = data?.assignments.accounts.filter(item => item.assigned_clan_tag).length || 0
  const waiting = (data?.signups.length || 0) - assigned
  const complete = !!data && !cached && !partial && !error
  const nextStep = homeNextStep(complete, season, rows.length, unsigned, error ? 'error' : cached ? 'saved' : 'loading')
  const lastPage = Math.max(0, Math.ceil(visible.length / 12) - 1)
  const currentPage = Math.min(page, lastPage)
  const pageRows = visible.slice(currentPage * 12, (currentPage + 1) * 12)
  const previousFilters = useRef([filter, search, sort])
  useEffect(() => { const next = [filter, search, sort]; if (next.some((value, index) => value !== previousFilters.current[index])) setPage(0); previousFilters.current = next }, [filter, search, sort])
  const groups = new Map<string, typeof rows>()
  for (const row of pageRows) { const key = row.current_clan_tag || 'none'; groups.set(key, [...(groups.get(key) || []), row]) }
  const canSignup = !cached && !error && !refreshing && !!season?.signup_open && season.status === 'draft'
  const selectVisible = () => setSelected(current => [...new Set([...current, ...visible.filter(row => !row.signup).map(row => row.tag)])])
  return <div className="dashboard-home">
    <div className="page-head"><div><p className="eyebrow">Your Warriors United home</p><h1>Hey, {session.user.display_name || session.user.username}</h1><p>Your accounts, your clans, and what to do next.</p></div><p className="season-choice">{seasons.find(item => String(item.id) === seasonId)?.label || 'No CWL season available'}</p></div>
    <div className="hub-sync"><span role="status"><span className={`status-dot ${!error && data ? 'active' : ''}`} />{cached ? (error ? 'Showing saved data · refresh failed' : 'Showing saved data · checking for updates…') : refreshing ? 'Refreshing…' : error ? 'Refresh needs attention' : data ? `Updated ${new Date(data.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Loading your accounts…'}</span><div><small>{paused ? 'Auto-refresh paused' : 'Auto-refresh every 30 seconds'}</small><button onClick={() => setPaused(value => !value)} aria-pressed={paused}>{paused ? 'Resume' : 'Pause'}</button><button disabled={refreshing} onClick={() => setRefreshKey(value => value + 1)} aria-label="Refresh dashboard">↻ Refresh</button></div></div>
    {error && <div className="notice error" role="alert"><div>{error}{data && <small>Showing available account details. Saved signups have not been removed.</small>}</div><button onClick={() => setRefreshKey(value => value + 1)}>Retry</button></div>}
    <section className="hub-next" aria-labelledby="hub-next-title">
      <div className="hub-next-symbol" aria-hidden="true"><DashboardIcon name="war"/></div>
      <div className="hub-next-copy">
        <p className="eyebrow">CWL · {season?.label || 'Season coming soon'}</p>
        <h2 id="hub-next-title">{nextStep.title}</h2>
        <p>{complete && !rows.length && data?.linkInstruction ? data.linkInstruction : nextStep.detail}</p>
      </div>
      {nextStep.destination === 'help' && <button className="primary" onClick={() => { const target = document.getElementById('first-account-help'); target?.scrollIntoView({block:'start'}); target?.focus({preventScroll:true}) }}>How to link accounts</button>}
      {nextStep.destination === 'signup' && <button className="primary" onClick={() => onNavigate('signup')}>Go to signups →</button>}
      {nextStep.destination === 'assignments' && <button className="primary" onClick={() => onNavigate('assignments')}>My assignments →</button>}
    </section>
    <section className="home-task-entry" aria-labelledby="home-task-title">
      <DashboardIcon name="tasks"/>
      <div><h2 id="home-task-title">Your tasks</h2><p>Check war and CWL attacks, raids, and Clan Games for your linked accounts.</p></div>
      <button onClick={() => onNavigate('todo')}>Open tasks →</button>
    </section>
    <div className="home-quick-links">
      <button className="home-search-entry" onClick={() => onNavigate('search')}><DashboardIcon name="search"/><span>Search your players and clans</span><kbd>Ctrl / ⌘ K</kbd></button>
      <nav className="home-activity-links" aria-label="Activity"><button onClick={() => onNavigate('wars')}><DashboardIcon name="war"/> Wars</button><button onClick={() => onNavigate('events')}><DashboardIcon name="calendar"/> Events</button></nav>
    </div>
    <div className="hub-stats" aria-label="Account overview">
      {([{ filter: 'all', icon: 'accounts', label: 'Linked accounts', value: rows.length }, { filter: 'unsigned', icon: 'signup', label: 'Not signed up', value: unsigned }, { filter: 'waiting', icon: 'waiting', label: 'Waiting for a clan', value: Math.max(0, waiting) }, { filter: 'assigned', icon: 'shield', label: 'Assigned accounts', value: assigned }] as const).map(item => <button key={item.filter} aria-pressed={filter === item.filter} onClick={() => setFilter(item.filter)}><span aria-hidden="true"><DashboardIcon name={item.icon}/></span><strong>{complete ? item.value : '—'}</strong><small>{item.label}</small></button>)}
    </div>
    {!complete && <p className="hub-data-note" role="status">{error ? "Account summary needs a successful refresh." : cached ? "Checking saved account data before showing totals." : "Checking account data before showing totals."}</p>}
    <div className="hub-section-heading"><div><h2>My accounts</h2><p>{canSignup ? 'Select accounts to sign up. Signed-up accounts show their assigned clan.' : 'Your linked accounts, saved signups, and clan assignments.'}</p></div><button onClick={() => onNavigate('assignments')}>My assignments ↗</button></div>
    <div className="hub-toolbar"><label>Find an account or clan<input type="search" placeholder="Name, player tag or clan…" value={search} onChange={event => setSearch(event.target.value)} /></label><label>Show<select value={filter} onChange={event => setFilter(event.target.value as AccountFilter)}><option value="all">All accounts</option><option value="unsigned">Not signed up</option><option value="waiting">Waiting for a clan</option><option value="assigned">Assigned</option></select></label><label>Sort<select value={sort} onChange={event => setSort(event.target.value)}><option value="th">Town Hall · highest first</option><option value="name">Account name · A–Z</option></select></label></div>
    {data && <><div className="hub-selection"><span>{selected.length} selected · {visible.length} matching accounts</span><div><button disabled={!canSignup || !visible.some(row => !row.signup)} onClick={selectVisible}>Select accounts not signed up</button><button disabled={!selected.length} onClick={() => setSelected([])}>Clear</button></div></div>
      {!rows.length && refreshing ? <p role="status">Loading account details…</p>
        : !rows.length && error ? null
        : !rows.length ? <div className="card empty">
          <h3 id="first-account-help" tabIndex={-1}>Link your first account</h3>
          <AccountLinkHelp busy={refreshing} onRefresh={() => setRefreshKey(value => value + 1)} />
        </div>
        : !visible.length ? <div className="card empty">
          <h3>No accounts match</h3>
          <p>Try another name or choose All accounts.</p>
          <button onClick={() => { setSearch(''); setFilter('all') }}>Show all accounts</button>
        </div>
        : <div className="hub-clans">
          {[...groups.entries()].map(([key, members]) => <section className="hub-clan" key={key}>
            <header>
              <ClanBadge url={members[0].current_clan_badge_url} name={members[0].current_clan_name || 'No current clan'} />
              <div>
                <h3>{members[0].current_clan_name || 'No current clan'}</h3>
                <small>Current clan{key !== 'none' ? ` · ${key}` : ''}</small>
              </div>
              {key !== 'none' && <button
                className="hub-clan-link"
                onClick={() => setDetail({ kind: 'clan', tag: key })}
                aria-label={`Details for ${members[0].current_clan_name || key}`}
              >Clan details</button>}
            </header>
            <div>{members.map(row => <article
              className={`hub-account ${selected.includes(row.tag) ? 'is-selected' : ''}`}
              key={row.tag}
            >
              <label className="hub-account-pick">
                <input
                  type="checkbox"
                  aria-label={`Select ${row.name}`}
                  disabled={!canSignup || !!row.signup}
                  checked={selected.includes(row.tag)}
                  onChange={event => setSelected(current => event.target.checked
                    ? [...new Set([...current, row.tag])]
                    : current.filter(tag => tag !== row.tag))}
                />
                <TownHallIcon level={row.town_hall} />
                <span>
                  <strong>{row.name}</strong>
                  <small>{row.tag}</small>
                  <small title="Saved clan weight, staff override, or FWA Stats fallback">
                    War weight: {row.war_weight == null ? 'Not Available' : weightText(row.war_weight)}
                  </small>
                </span>
              </label>
              <div className="hub-account-status">
                <span className={`hub-state ${row.signup ? 'saved' : ''}`}>
                  {row.signup ? `✓ ${row.signup.pool === 'main' ? 'Main' : 'Lazy'} CWL · Signed Up` : 'Not signed up'}
                </span>
                {row.signup && <small>
                  {row.assignment?.assigned_clan_tag
                    ? `${row.assignment.assigned_clan_name || row.assignment.assigned_clan_tag}`
                    : 'Waiting for a clan'}
                  {row.assignment?.assigned_clan_tag && data.assignments && memberPlacementStatus(data.assignments) === 'provisional'
                    ? ' · May change' : ''}
                </small>}
              </div>
              <div className="hub-account-actions">
                <button
                  className="hub-account-detail"
                  onClick={() => setDetail({ kind: 'player', tag: row.tag })}
                  aria-label={`Details for ${row.name}`}
                >Details</button>
                {row.signup && <button
                  className="hub-account-action"
                  onClick={() => onNavigate(row.assignment?.assigned_clan_tag ? 'assignments' : 'saved')}
                >{row.assignment?.assigned_clan_tag ? 'View clan' : 'Manage signup'} →</button>}
              </div>
            </article>)}</div>
          </section>)}
        </div>}
      {lastPage > 0 && <nav className="hub-pagination" aria-label="Account pages"><button disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>← Previous</button><span>Page {currentPage + 1} of {lastPage + 1}</span><button disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}>Next →</button></nav>}
      {selected.length > 0 && <div className="hub-selected-bar"><div><strong>{selected.length} account{selected.length === 1 ? '' : 's'} selected</strong><small>Choose a pool, then review. Nothing is submitted yet.</small></div><button className="primary" disabled={!canSignup} onClick={() => onStart('main', selected, data.accounts, data.signups)}>Main CWL →</button><button className="primary" disabled={!canSignup} onClick={() => onStart('lazy', selected, data.accounts, data.signups)}>Lazy CWL →</button></div>}
    </>}
    <div className="hub-bottom"><details className="hub-help"><summary>Missing an account?</summary><AccountLinkHelp busy={refreshing} onRefresh={() => setRefreshKey(value => value + 1)} /><p>Already signed-up accounts can be moved or withdrawn in My signups.</p><button onClick={() => onNavigate('saved')}>Open My signups →</button></details>{session.can_edit && <section className="hub-staff"><h3>Staff tools</h3><div><button onClick={() => onNavigate('roster')}>Build roster →</button><button onClick={() => onNavigate('publication')}>Publish roster →</button><button onClick={() => onNavigate('staff')}>Seasons & clans →</button></div></section>}</div>
    {detailPlayer && <PlayerClanDetailsDialog kind="player" account={detailPlayer} session={session} freshness={detailFreshness} loadedAt={data?.checkedAt} returnFocusFallbackId="dashboard-main" onClose={() => setDetail(null)}>
      {detailPlayer.signup && <section className="player-clan-details-section">
        <h3>{season?.label || 'This season'} · {detailPlayer.signup.pool === 'main' ? 'Main CWL' : 'Lazy CWL'}</h3>
        <p>{detailPlayer.assignment?.assigned_clan_name || detailPlayer.assignment?.assigned_clan_tag || 'Waiting for a clan'}{detailPlayer.assignment?.assigned_clan_tag && data && memberPlacementStatus(data.assignments) === 'provisional' ? ' · May change' : ''}</p>
      </section>}
      <MemberDetailActivity onDenied={denyDetails} key={detailPlayer.tag} target="player" tag={detailPlayer.tag} clanTag={detailPlayer.current_clan_tag} />
    </PlayerClanDetailsDialog>}
    {detail?.kind === 'clan' && detailClanAccount && <PlayerClanDetailsDialog kind="clan" tag={detail.tag} name={detailClanAccount.current_clan_name || detail.tag} badgeUrl={detailClanAccount.current_clan_badge_url} linkedAccounts={data?.accounts} freshness={detailFreshness} loadedAt={data?.checkedAt} returnFocusFallbackId="dashboard-main" onClose={() => setDetail(null)}>
      <MemberDetailActivity onDenied={denyDetails} key={detail.tag} target="clan" tag={detail.tag} />
    </PlayerClanDetailsDialog>}
  </div>
}
