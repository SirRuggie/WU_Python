import { loadTasks } from './todoLoading'
import TodoTaskCard from './TodoTaskCard'
import ClanGamesSummary from './ClanGamesSummary'
import { withoutGamesScores } from './todoSnapshot'
import DashboardIcon from './DashboardIcon'
import TaskEventTimer from './activity/TaskEventTimer'
import { useClock } from './activity/useClock'
import PushReminders from './PushReminders'
import { readSnapshot, writeSnapshot } from './snapshotCache'
import { useEffect, useState } from 'react'
import { ApiError } from './api'
import { clanDeepLink } from './publication'
import TownHallIcon from './TownHallIcon'
import { todoHasGaps, todoEmptyText, todoTabs, visibleTodoRows, type TodoKind, type TodoSnapshot, type TodoRow } from './todo'
import './TodoWorkspace.css'
import { readTodoPreferences, saveTodoPreferences } from './todoPreferences'
function Badge({ url }: { url?: string | null }) {
  const [failed, setFailed] = useState('')
  return url && failed !== url ? <img src={url} alt="" width={40} height={40} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(url)} /> : <DashboardIcon name="shield"/>
}
export default function TodoWorkspace({ userId, initialSearch = '', initialTab }: { userId: string; initialSearch?: string; initialTab?: TodoKind }) {
  const preferenceId = userId
  const [preferences] = useState(() => { try { return readTodoPreferences(preferenceId, window.localStorage) } catch { return { tab: 'war' as TodoKind, selected: null, sort: 'deadline' } } })
  const cacheKey = `todo:${userId}`
  const [data,setData] = useState<TodoSnapshot | null>(() => {
    const saved = readSnapshot<TodoSnapshot>(cacheKey, (value): value is TodoSnapshot => {
      const v = value as TodoSnapshot
      return !!v && Array.isArray(v.accounts) && typeof v.checked_at === 'string'
        && ['war','cwl','raid','games','private'].every(key => Array.isArray(v.views?.[key as TodoKind]?.rows))
    })
    if (!saved) return null
    const safe = withoutGamesScores(saved)
    writeSnapshot(cacheKey, safe)
    return safe
  })
  const [cached,setCached] = useState(!!data)
  const [error,setError] = useState('')
  const [loading,setLoading] = useState(false)
  const [paused,setPaused] = useState(false)
  const [refresh,setRefresh] = useState(0)
  const [tab,setTab] = useState<TodoKind>(initialTab || preferences.tab)
  const [selected,setSelected] = useState<string[] | null>(initialSearch ? null : preferences.selected)
  const [accountSearch,setAccountSearch] = useState('')
  const [search,setSearch] = useState(initialSearch)
  const [sort,setSort] = useState(preferences.sort)
  useEffect(() => { try { if (!initialSearch) saveTodoPreferences(preferenceId, { tab, selected, sort }, window.localStorage) } catch { /* Storage can be blocked. */ } }, [userId, tab, selected, sort])
  const [page,setPage] = useState(0)
  const now = useClock()
  useEffect(() => {
    let cancelled=false, inFlight=false
    const load = async () => {
      if (cancelled || inFlight || document.hidden) return
      inFlight=true;setLoading(true)
      try {
        await loadTasks((result, updating) => {
          if (!cancelled) { setData(result); if (!updating) writeSnapshot(cacheKey,withoutGamesScores(result)); setCached(false); setError('') }
        }, () => !cancelled)
      } catch (cause) { if (!cancelled) { if (cause instanceof ApiError && [401,403].includes(cause.status)) { setData(null); setCached(false) }; setError(cause instanceof Error ? cause.message : 'Could not update your tasks. Try again.') } }
      finally { inFlight=false;if (!cancelled) setLoading(false) }
    }
    void load()
    const check = () => { if (!paused) void load() }
    const timer=window.setInterval(check,60000)
    document.addEventListener('visibilitychange',check);window.addEventListener('online',check)
    return () => { cancelled=true;clearInterval(timer);document.removeEventListener('visibilitychange',check);window.removeEventListener('online',check) }
  },[paused,refresh])
  useEffect(() => { setPage(0) },[tab,selected,search,sort])
  const gaps=todoHasGaps(data)
  const view=data?.views[tab]
  const config=todoTabs.find(item=>item.key===tab)!
  const rows=visibleTodoRows(view?.rows || [],selected,search,sort, !!initialSearch && search === initialSearch)
  const lastPage=Math.max(0,Math.ceil(rows.length/12)-1), currentPage=Math.min(page,lastPage)
  const groups=new Map<string,TodoRow[]>()
  rows.slice(currentPage*12,(currentPage+1)*12).forEach(row=>{const key=row.clan_tag || 'none';groups.set(key,[...(groups.get(key)||[]),row])})
  const accounts=data?.accounts || []
  const filteredAccounts=accounts.filter(account=>`${account.name} ${account.tag} ${account.current_clan_name || ''}`.toLocaleLowerCase().includes(accountSearch.toLocaleLowerCase()))
  const selectedCount=selected===null ? accounts.length : accounts.filter(account=>selected.includes(account.tag)).length
  const notes=[...new Set([view?.note,...(view?.notes || [])].filter(Boolean))]
  const unreadable=data?.views.private.rows.length || 0
  return <div className="todo-workspace">
    <div className="page-head"><div><p className="eyebrow">Activity</p><h1>Tasks</h1><p>Your accounts’ remaining attacks and personal progress. For whole-clan scores, open Wars.</p></div><button onClick={()=>setRefresh(value=>value+1)} disabled={loading}>↻ {loading ? 'Checking…' : 'Check now'}</button></div>
    <div className="todo-refresh"><span role="status"><span className={`status-dot ${data && !error && !gaps && !loading ? 'active' : ''}`} />{cached ? (error ? 'Showing saved data · refresh failed' : 'Showing saved data · checking for updates…') : loading ? 'Checking linked accounts and clan activity…' : error ? 'Refresh needs attention' : gaps ? 'Some activity could not be checked · try again shortly' : data ? `Last checked ${new Date(data.checked_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}` : 'Loading your activity…'}</span><button aria-pressed={paused} onClick={()=>setPaused(value=>!value)}>{paused ? '▶ Resume auto-refresh' : 'Ⅱ Pause auto-refresh'}</button></div>
    {error && <div className="notice error" role="alert"><div>{error}{data && <small>Showing your last update. It may be out of date.</small>}</div><button onClick={()=>setRefresh(value=>value+1)}>Retry</button></div>}
    {!data && !error && <div className="card todo-loading" role="status"><strong>Loading your tasks…</strong><p>Checking your linked accounts and clans.</p></div>}
    {data && <>
      <div className="todo-tabs" role="group" aria-label="Activity types">{todoTabs.map(item=>{
        const activity=data.views[item.key]
        const count=visibleTodoRows(activity.rows,selected,search,'deadline', !!initialSearch && search === initialSearch).length
        return <button key={item.key} aria-pressed={tab===item.key} onClick={()=>setTab(item.key)}><span aria-hidden="true"><DashboardIcon name={item.icon}/></span><strong>{item.label}</strong><small>{activity.loading ? 'Checking…' : !activity.ok ? 'Unavailable' : activity.incomplete ? `${count} · Partial` : activity.unavailable ? 'Not active' : `${count} account${count===1?'':'s'}`}</small></button>
      })}</div>
      <details className="todo-account-picker"><summary>{selected===null ? 'All linked accounts' : `${selectedCount} account${selectedCount===1?'':'s'} selected`} <span>Choose accounts</span></summary><div className="todo-picker-tools"><label>Find linked accounts<input type="search" value={accountSearch} onChange={event=>setAccountSearch(event.target.value)} placeholder="Account or clan name…" /></label><button onClick={()=>setSelected(null)}>All accounts</button><button onClick={()=>setSelected([])}>Clear</button></div><div className="todo-picker-list">{filteredAccounts.map(account=><label key={account.tag}><input type="checkbox" checked={selected===null || selected.includes(account.tag)} onChange={event=>setSelected(current=>{const previous=current===null ? accounts.map(item=>item.tag) : current;return event.target.checked ? [...new Set([...previous,account.tag])] : previous.filter(tag=>tag!==account.tag)})}/><TownHallIcon level={account.town_hall}/><span><strong>{account.name}</strong><small>{account.tag}</small></span></label>)}{!filteredAccounts.length && <p>No matching linked accounts.</p>}</div></details>
      <div className="todo-section-head"><div><h2><DashboardIcon name={config.icon}/> {config.label}</h2><p>{config.description}</p></div><label>Sort tasks<select value={sort} onChange={event=>setSort(event.target.value)}><option value="deadline">Ending soonest</option><option value="th">Town Hall · highest first</option><option value="name">Account name · A–Z</option></select></label></div>
      {tab==='games' && view?.season ? <ClanGamesSummary view={view} now={now}/> : (tab==='raid' || tab==='games' || tab==='cwl') && <TaskEventTimer kind={tab} now={now}/>}
      <label className="todo-search">Search tasks<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Account, tag or clan…"/></label>
      {view && <>
        {!view.loading && (!view.ok || !!view.incomplete) && <div className="todo-warning" role="status"><strong>{view.ok ? 'Some activity could not be checked' : 'This activity is unavailable'}</strong><p>{view.incomplete || view.unavailable || view.note || 'Try again later. Check this activity in-game meanwhile.'}</p></div>}
        {tab!=='private' && tab!=='games' && unreadable>0 && <div className="todo-warning"><span>Some war logs could not be read. Their attacks may not appear here.</span><button onClick={()=>setTab('private')}>View affected accounts →</button></div>}
        {!view.loading && notes.length>0 && <div className="todo-notes">{notes.map(note=><p key={note}>{note}</p>)}</div>}
        {view.loading ? <div className="card todo-loading" role="status"><strong>Checking {config.label.toLowerCase()}…</strong><p>You can view other activities while this check finishes.</p></div> : !accounts.length ? <div className="card empty"><h3>No linked accounts to show</h3><p>Use ClashKing’s /link command in Discord, then check again.</p></div> : !rows.length ? <div className="card empty"><h3>{!view.ok || view.incomplete ? 'Check in-game' : selectedCount===0 ? 'Choose accounts to see their tasks' : 'Nothing to show here'}</h3><p>{todoEmptyText(view,tab,selected!==null || !!search)}</p></div> : <div className="todo-clan-list">{[...groups.entries()].map(([key,members])=><section className="todo-clan" key={key}><header><Badge url={members[0].badge_url}/><div><h3>{members[0].clan_name || members[0].clan_tag || 'Clan unknown'}</h3>{tab==='war' && members[0].fwa_outcome && <div className={`todo-fwa ${members[0].fwa_outcome.status}`}><strong>{({win:'FWA outcome: WIN',lose:'FWA outcome: LOSE',blacklisted:'BLACKLISTED opponent',unknown:'FWA outcome: Unknown'})[members[0].fwa_outcome.status]}</strong>{members[0].fwa_outcome.opponent && <span>vs {members[0].fwa_outcome.opponent}</span>}</div>}<small>{members.length} account{members.length===1?'':'s'} on this page</small></div>{key!=='none' && <a href={clanDeepLink(key)} target="_blank" rel="noopener noreferrer">Open Clan ↗</a>}</header>{members.map((row,index)=><TodoTaskCard key={`${row.tag}-${index}`} row={row} kind={tab} now={now}/>)}</section>)}</div>}
        {lastPage>0 && <nav className="todo-pagination" aria-label="Activity pages"><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>← Previous</button><span>{currentPage+1} / {lastPage+1}</span><button disabled={currentPage===lastPage} onClick={()=>setPage(currentPage+1)}>Next →</button></nav>}
      </>}
    </>}
    <p className="todo-freshness">Your account selection and view are remembered on this browser. Checks every minute while this page is open. Game data may take a few minutes to catch up after an attack.</p>
    <PushReminders key={userId} accounts={accounts} />
  </div>
}
