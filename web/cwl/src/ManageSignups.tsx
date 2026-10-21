import {useCallback, useEffect, useState} from 'react'
import {api, type Season, type Signup} from './api'
import StaffSignupControls from './StaffSignupControls'
import StaffPlayerButton from './StaffPlayerButton'
import useUnsavedWork from './useUnsavedWork'
import MemberPicker, {type MemberOption} from './MemberPicker'
import DiscordContact from './DiscordContact'

type Props = {
  season: Season
  onDirty: (dirty: boolean) => void
  onBusy: (busy: boolean) => void
  onSeasonRefresh: () => Promise<void>
  onRoster: () => void
}

export default function ManageSignups({season, onDirty, onBusy, onSeasonRefresh, onRoster}: Props) {
  const [formDirty,setFormDirty] = useState(false)
  const [formBusy,setFormBusy] = useState(false)
  const [editorDirty,setEditorDirty] = useState(false)
  const [editorBusy,setEditorBusy] = useState(false)
  useUnsavedWork(formDirty||editorDirty||formBusy||editorBusy,onDirty)
  useEffect(()=>{onBusy(formBusy||editorBusy);return()=>onBusy(false)},[formBusy,editorBusy,onBusy])
  const [rows, setRows] = useState<Signup[]>([])
  const [member, setMember] = useState('')
  const [findMember, setFindMember] = useState(false)
  const [names, setNames] = useState<Record<string,string>>({})
  useEffect(() => {
    let active = true
    api<{options: MemberOption[]}>('/staff-signup-members').then(data => {
      if (active) setNames(current => ({...current,...Object.fromEntries(data.options.map(option => [option.id, option.display_name || option.username]))}))
    }).catch(() => { /* Discord IDs remain usable if display names are unavailable. */ })
    return () => { active = false }
  }, [])
  const [pool, setPool] = useState('all')
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [page, setPage] = useState(0)
  const reload = useCallback(async () => { setRefresh(value => value + 1) }, [])
  useEffect(() => {
    let active = true
    setLoading(true)
    api<{signups: Signup[]}>(`/seasons/${season.id}/signups?all=1`)
      .then(data => { if (active) {setRows(data.signups); setError('')} })
      .catch(cause => { if (active) {setRows([]); setError(cause.message)} })
      .finally(() => {if (active) setLoading(false)})
    return () => { active = false }
  }, [season.id, refresh])
  const term = search.trim().toLowerCase()
  const matching = rows.filter(row => (!member || row.user_id === member) && (pool === 'all' || row.pool === pool) && [row.player_name, row.tag, row.user_id, row.signup_clan_name].some(value => value?.toLowerCase().includes(term)))
  const groups = new Map<string, Signup[]>()
  matching.forEach(row => {
    const key = row.user_id || `unlinked:${row.tag}`
    groups.set(key, [...(groups.get(key) || []), row])
  })
  const lastPage = Math.max(0, Math.ceil(groups.size / 10) - 1)
  const currentPage = Math.min(page, lastPage)
  return <div className="manage-signups">
    <StaffSignupControls season={season} onDirty={setFormDirty} onBusy={setFormBusy}
      onChanged={async () => {await onSeasonRefresh(); await reload()}} />
    <section className="card">
      <div className="section-heading"><h2>Saved signups</h2><button onClick={onRoster}>Open roster</button></div>
      <p>Accounts are grouped by member. Open an account to manage its placement or remove its signup.</p>
      <button aria-expanded={findMember} onClick={()=>setFindMember(value=>!value)}>Find by Discord member{member ? ' · Filter active' : ''}</button>
      {findMember && <MemberPicker label="Filter signups by member" value={member} disabled={false} endpoint="/staff-signup-members" showRoles={false}
        onChange={value=>{setMember(String(value||''));setPage(0)}}
        onOptions={options=>setNames(current=>({...current,...Object.fromEntries(options.map(option=>[option.id,option.display_name||option.username]))}))}/>}
      {member && <button onClick={()=>{setMember('');setPage(0)}}>Show all members</button>}
      <div className="workflow-tabs staff-add-modes" role="group" aria-label="Signup pool filter">
        {['all','main','lazy'].map(value => <button key={value} aria-pressed={pool===value} onClick={()=>{setPool(value);setPage(0)}}>{value==='all'?'All signups':value==='main'?'Main':'Lazy'}</button>)}
      </div><div className="staff-signup-list-tools">
        <label>Find a signup<input type="search" value={search} onChange={event => {setSearch(event.target.value); setPage(0)}} placeholder="Player name, tag or Discord ID" /></label>
        <button disabled={loading} onClick={() => void reload()}>Refresh</button>
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      {loading ? <p role="status">Loading signups…</p> : !error && <>
        <p>{matching.length} accounts · {groups.size} {groups.size===1?'member group':'member groups'}</p>
        {!matching.length && <p>{rows.length ? 'No signups match your search.' : 'No accounts signed up yet.'}</p>}
        {[...groups.entries()].slice(currentPage * 10, (currentPage + 1) * 10).map(([key, accounts]) =>
          <section className="staff-member-signups" key={key}>
            <div className="section-heading"><h3>{accounts[0].user_id ? names[accounts[0].user_id] || `Discord member ${accounts[0].user_id}` : 'No Discord account'}</h3><DiscordContact userId={accounts[0].user_id} compact/></div>
            {accounts.map(account => <div className="staff-row" key={account.tag}>
              <div><strong>{account.player_name || account.tag}</strong><small>{account.tag} · {account.pool === 'main' ? 'Main' : 'Lazy'} CWL · {account.has_staff_placement ? 'Placed in working roster' : 'Waiting for placement'}</small>{account.family_clan_status === 'outside' && <small>Outside the family clans</small>}{account.family_clan_status === 'unknown' && <small>Family clan status not available</small>}</div>
              {season.status !== 'archived' && <StaffPlayerButton onDirty={setEditorDirty} onBusy={setEditorBusy} seasonId={String(season.id)} tag={account.tag} onChanged={reload}>Manage account</StaffPlayerButton>}
            </div>)}
          </section>) }
        {lastPage > 0 && <nav className="staff-signup-list-tools" aria-label="Signup member pages">
          <button disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Previous</button>
          <span>Page {currentPage + 1} of {lastPage + 1}</span>
          <button disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button>
        </nav>}
      </>}
    </section>
  </div>
}
