import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, type Account, type Clan } from './api'
import DashboardIcon from './DashboardIcon'
import TownHallIcon from './TownHallIcon'
import { clanDeepLink } from './publication'
import { matchingResults, searchIndex } from './dashboardSearch'

export default function DashboardSearch({ includeFamily, query, onQuery, kind, onKind: setKind, page, onPage: setPage, onTasks }: {
  kind: 'all' | 'player' | 'clan'; onKind: (kind: 'all' | 'player' | 'clan') => void; page: number; onPage: (page: number) => void;
  includeFamily: boolean; query: string; onQuery: (query: string) => void; onTasks: (tag: string) => void
}) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [family, setFamily] = useState<Clan[]>([])
  const [error, setError] = useState('')
  const [familyError, setFamilyError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setBusy(true); setError(''); setFamilyError(''); setAccounts([]); setFamily([])
    void Promise.allSettled([
      api<{accounts: Account[]}>('/dashboard/accounts'),
      includeFamily ? api<{clans: Clan[]}>('/approved-clans') : Promise.resolve({clans: []}),
    ]).then(([players, clans]) => {
      if (!active) return
      // A revoked session must not leave any protected results visible.
      const denied = [players, clans].find(result => result.status === 'rejected' && result.reason instanceof ApiError && [401, 403].includes(result.reason.status))
      if (denied?.status === 'rejected') setError(denied.reason.message)
      else {
        if (players.status === 'fulfilled') setAccounts(players.value.accounts)
        else setError(players.reason instanceof Error ? players.reason.message : 'Could not load linked accounts.')
        if (clans.status === 'fulfilled') setFamily(clans.value.clans)
        else setFamilyError('The family directory is unavailable. Results include only linked accounts and their clans.')
      }
      setBusy(false)
    })
    return () => { active = false }
  }, [includeFamily, attempt])
  const index = useMemo(() => searchIndex(accounts, family), [accounts, family])
  const results = matchingResults(index, query, kind)
  const lastPage = Math.max(0, Math.ceil(results.length / 20) - 1)
  const currentPage = Math.min(page, lastPage)
  return <section className="dashboard-search-workspace">
    <header className="page-head"><div><p className="eyebrow">Your dashboard</p><h1>Search</h1><p>Find your linked players and their clans{includeFamily ? ', plus the family clan directory' : ''}.</p></div></header>
    <label className="global-search-field" htmlFor="dashboard-search"><DashboardIcon name="search"/><span className="sr-only">Search players and clans</span><input id="dashboard-search" autoFocus type="search" placeholder="Player or clan name, or #tag" value={query} maxLength={100} onChange={event => onQuery(event.target.value)}/></label>
    <div className="search-kind-filters" role="group" aria-label="Search result type">{(['all','player','clan'] as const).map(value => <button key={value} aria-pressed={kind === value} onClick={() => setKind(value)}>{value === 'all' ? 'All' : value === 'player' ? 'Players' : 'Clans'} <small>{matchingResults(index, query, value).length}</small></button>)}</div>
    {busy && <p role="status">Loading searchable accounts and clans…</p>}
    {(error || familyError) && <div className="notice error" role="alert"><p>{error || familyError}</p><button disabled={busy} onClick={() => setAttempt(value => value + 1)}>Retry search data</button></div>}
    {!busy && <p role="status">{results.length} result{results.length === 1 ? '' : 's'}</p>}
    {!busy && !error && !results.length && <div className="card empty"><h2>{index.length ? 'No matches' : 'No accounts to search yet'}</h2><p>{index.length ? 'Try another name or tag, or choose All.' : 'Link your accounts in Discord, then refresh search data.'}</p><button onClick={() => { onQuery(''); setKind('all'); if (!index.length) setAttempt(value => value + 1) }}>{index.length ? 'Clear filters' : 'Refresh search data'}</button></div>}
    <div className="search-results">{results.slice(currentPage * 20, (currentPage + 1) * 20).map(item => <article className="search-result" key={`${item.kind}:${item.tag}`}>
      {item.kind === 'player' ? <TownHallIcon level={item.townHall ?? null}/> : <DashboardIcon name="shield"/>}
      <div><strong>{item.name}</strong><small>{item.tag} · {item.detail}</small></div>
      <div className="search-result-actions">{(item.kind === 'player' || accounts.some(account => account.current_clan_tag === item.tag)) && <button onClick={() => onTasks(item.tag)}>View tasks</button>}{item.kind === 'clan' && <a href={clanDeepLink(item.tag)} target="_blank" rel="noopener noreferrer">Open clan ↗</a>}</div>
    </article>)}</div>
    {lastPage > 0 && <nav className="search-pagination" aria-label="Search pages"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage + 1} of {lastPage + 1}</span><button disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button></nav>}
  </section>
}
