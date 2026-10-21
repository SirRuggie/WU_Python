import DashboardIcon from './DashboardIcon'
import PushReminders from './PushReminders'
import { readSnapshot, writeSnapshot } from './snapshotCache'
import { useEffect, useState } from 'react'
import { api, ApiError } from './api'
import { clanDeepLink } from './publication'
import TownHallIcon from './TownHallIcon'
import { todoEmptyText, todoTabs, todoTime, visibleTodoRows, type TodoKind, type TodoSnapshot, type TodoRow } from './todo'
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
  const [data,setData] = useState<TodoSnapshot | null>(() => readSnapshot<TodoSnapshot>(cacheKey, (value): value is TodoSnapshot => { const v = value as TodoSnapshot; return !!v && Array.isArray(v.accounts) && typeof v.checked_at === 'string' && ['war','cwl','raid','games','private'].every(key => Array.isArray(v.views?.[key as TodoKind]?.rows)) }))
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
  const [now,setNow] = useState(Date.now())
  useEffect(() => {
    let cancelled=false, inFlight=false
    const load = async () => {
      if (cancelled || inFlight || document.hidden) return
      inFlight=true;setLoading(true)
      try {
        const result = await api<TodoSnapshot>('/todo')
        if (!cancelled) { setData(result);writeSnapshot(cacheKey,result);setCached(false);setError('');setNow(Date.now()) }
      } catch (cause) { if (!cancelled) { if (cause instanceof ApiError && [401,403].includes(cause.status)) { setData(null); setCached(false) }; setError(cause instanceof Error ? cause.message : 'Could not update your tasks. Try again.') } }
      finally { inFlight=false;if (!cancelled) setLoading(false) }
    }
    void load()
    const check = () => { if (!paused) void load() }
    const timer=window.setInterval(check,60000)
    document.addEventListener('visibilitychange',check);window.addEventListener('online',check)
    return () => { cancelled=true;clearInterval(timer);document.removeEventListener('visibilitychange',check);window.removeEventListener('online',check) }
  },[paused,refresh])
  useEffect(() => { const timer=window.setInterval(()=>setNow(Date.now()),30000);return ()=>clearInterval(timer) },[])
  useEffect(() => { setPage(0) },[tab,selected,search,sort])
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
    <div className="todo-refresh"><span role="status"><span className={`status-dot ${data && !error ? 'active' : ''}`} />{cached ? (error ? 'Showing saved data · refresh failed' : 'Showing saved data · checking for updates…') : loading ? 'Checking linked accounts and clan activity…' : error ? 'Refresh needs attention' : data ? `Last checked ${new Date(data.checked_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}` : 'Loading your activity…'}</span><button aria-pressed={paused} onClick={()=>setPaused(value=>!value)}>{paused ? '▶ Resume auto-refresh' : 'Ⅱ Pause auto-refresh'}</button></div>
    {error && <div className="notice error" role="alert"><div>{error}{data && <small>Showing your last update. It may be out of date.</small>}</div><button onClick={()=>setRefresh(value=>value+1)}>Retry</button></div>}
    {!data && !error && <div className="card todo-loading" role="status"><strong>Loading your tasks…</strong><p>Checking your linked accounts and clans.</p></div>}
    {data && <>
      <div className="todo-tabs" role="group" aria-label="Activity types">{todoTabs.map(item=>{
        const activity=data.views[item.key]
        const count=visibleTodoRows(activity.rows,selected,search,'deadline', !!initialSearch && search === initialSearch).length
        return <button key={item.key} aria-pressed={tab===item.key} onClick={()=>setTab(item.key)}><span aria-hidden="true"><DashboardIcon name={item.icon}/></span><strong>{item.label}</strong><small>{!activity.ok ? 'Unavailable' : activity.incomplete ? `${count} · Partial` : activity.unavailable ? 'Not active' : `${count} account${count===1?'':'s'}`}</small></button>
      })}</div>
      <details className="todo-account-picker"><summary>{selected===null ? 'All linked accounts' : `${selectedCount} account${selectedCount===1?'':'s'} selected`} <span>Choose accounts</span></summary><div className="todo-picker-tools"><label>Find linked accounts<input type="search" value={accountSearch} onChange={event=>setAccountSearch(event.target.value)} placeholder="Account or clan name…" /></label><button onClick={()=>setSelected(null)}>All accounts</button><button onClick={()=>setSelected([])}>Clear</button></div><div className="todo-picker-list">{filteredAccounts.map(account=><label key={account.tag}><input type="checkbox" checked={selected===null || selected.includes(account.tag)} onChange={event=>setSelected(current=>{const previous=current===null ? accounts.map(item=>item.tag) : current;return event.target.checked ? [...new Set([...previous,account.tag])] : previous.filter(tag=>tag!==account.tag)})}/><TownHallIcon level={account.town_hall}/><span><strong>{account.name}</strong><small>{account.tag}</small></span></label>)}{!filteredAccounts.length && <p>No matching linked accounts.</p>}</div></details>
      <div className="todo-section-head"><div><h2><DashboardIcon name={config.icon}/> {config.label}</h2><p>{config.description}</p></div><label>Sort tasks<select value={sort} onChange={event=>setSort(event.target.value)}><option value="deadline">Ending soonest</option><option value="th">Town Hall · highest first</option><option value="name">Account name · A–Z</option></select></label></div>
      <label className="todo-search">Search tasks<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Account, tag or clan…"/></label>
      {view && <>
        {(!view.ok || !!view.incomplete) && <div className="todo-warning" role="status"><strong>{view.ok ? 'Some activity could not be checked' : 'This activity is unavailable'}</strong><p>{view.incomplete || view.unavailable || view.note || 'Try again later. Check this activity in-game meanwhile.'}</p></div>}
        {tab!=='private' && tab!=='games' && unreadable>0 && <div className="todo-warning"><span>Some war logs could not be read. Their attacks may not appear here.</span><button onClick={()=>setTab('private')}>View affected accounts →</button></div>}
        {notes.length>0 && <div className="todo-notes">{notes.map(note=><p key={note}>{note}</p>)}</div>}
        {!accounts.length ? <div className="card empty"><h3>No linked accounts to show</h3><p>Use ClashKing’s /link command in Discord, then check again.</p></div> : !rows.length ? <div className="card empty"><h3>{!view.ok || view.incomplete ? 'Check in-game' : selectedCount===0 ? 'Choose accounts to see their tasks' : 'Nothing to show here'}</h3><p>{todoEmptyText(view,tab,selected!==null || !!search)}</p></div> : <div className="todo-clan-list">{[...groups.entries()].map(([key,members])=><section className="todo-clan" key={key}><header><Badge url={members[0].badge_url}/><div><h3>{members[0].clan_name || members[0].clan_tag || 'Clan unknown'}</h3>{tab==='war' && members[0].fwa_outcome && <div className={`todo-fwa ${members[0].fwa_outcome.status}`}><strong>{({win:'FWA outcome: WIN',lose:'FWA outcome: LOSE',blacklisted:'BLACKLISTED opponent',unknown:'FWA outcome: Unknown'})[members[0].fwa_outcome.status]}</strong>{members[0].fwa_outcome.opponent && <span>vs {members[0].fwa_outcome.opponent}</span>}</div>}<small>{members.length} account{members.length===1?'':'s'} on this page</small></div>{key!=='none' && <a href={clanDeepLink(key)} target="_blank" rel="noopener noreferrer">Open Clan ↗</a>}</header>{members.map((row,index)=>{
          const privateRow=tab==='private'
          const games=tab==='games'
          const preparation=row.state==='preparation'
          const measurable=row.used!==null && row.total!==null && row.total>0 && !privateRow
          const timestamp=preparation ? row.starts_at : row.ends_at
          return <article className="todo-task" key={`${row.tag}-${index}`}><div className="todo-task-name"><TownHallIcon level={row.town_hall}/><div><strong>{row.name}</strong><small>{row.tag}</small></div><a href={`https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=${encodeURIComponent(row.tag)}`} target="_blank" rel="noopener noreferrer" aria-label={`Open ${row.name} in Clash of Clans`}>↗</a></div><div className="todo-task-progress"><span className={`todo-state ${preparation?'prep':privateRow?'blocked':''}`}>{privateRow ? (row.detail==='private' ? 'Private war log' : 'Unable to check') : games ? row.used===null ? 'Points unknown' : `${row.used.toLocaleString()} recorded points` : preparation ? 'Preparation day' : `${row.remaining ?? '—'} attack${row.remaining===1?'':'s'} left`}</span>{measurable && <><progress max={row.total!} value={Math.min(row.used!,row.total!)} aria-label={`${row.name}: ${row.used} of ${row.total} ${games?'goal points':'attacks used'}`}/><small>{games ? `Family goal: ${row.total!.toLocaleString()} points` : `${row.used} of ${row.total} attacks used`}</small></>}</div><div className="todo-task-time">{privateRow ? <p>{row.detail==='private' ? 'Check attacks in-game. A clan leader can make the war log public.' : row.detail && row.detail!=='error' ? row.detail : 'Could not check this war. Try again or check in-game.'}</p> : games ? <p>{row.detail || 'Recorded activity may not include every point. Check in-game for your exact total.'}</p> : <><small>{preparation ? 'Battle starts in' : 'Ends in'}</small><strong>{todoTime(timestamp,now)}</strong>{timestamp && <time dateTime={new Date(timestamp*1000).toISOString()}>{new Date(timestamp*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time>}</>}</div></article>
        })}</section>)}</div>}
        {lastPage>0 && <nav className="todo-pagination" aria-label="Activity pages"><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>← Previous</button><span>{currentPage+1} / {lastPage+1}</span><button disabled={currentPage===lastPage} onClick={()=>setPage(currentPage+1)}>Next →</button></nav>}
      </>}
    </>}
    <p className="todo-freshness">Your account selection and view are remembered on this browser. Checks every minute while this page is open. Game data may take a few minutes to catch up after an attack.</p>
    <PushReminders key={userId} accounts={accounts} />
  </div>
}
