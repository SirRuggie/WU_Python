import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Season } from './api'
import { groupAssignments } from './assignmentGroups'
import { clanDeepLink, type MyAssignments } from './publication'
import './MemberAssignments.css'
import {memberPath} from './memberLinks'

type Props = { seasonId: string; seasons: Season[]; onSeasonChange: (id: string) => void }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Assignments could not be loaded. Try again.'

export default function MemberAssignments({ seasonId, seasons, onSeasonChange }: Props) {
  const [data, setData] = useState<MyAssignments | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(0)
  const activeSeason = useRef(seasonId)
  activeSeason.current = seasonId
  const load = useCallback(async () => {
    if (!seasonId) return
    const sid = seasonId
    const id = ++requestId.current
    setLoading(true); setError('')
    try {
      const result = await api<MyAssignments>(`/seasons/${encodeURIComponent(sid)}/my-assignments`)
      if (id === requestId.current && activeSeason.current === sid) setData(result)
    } catch (cause) { if (id === requestId.current && activeSeason.current === sid) setError(errorText(cause)) }
    finally { if (id === requestId.current && activeSeason.current === sid) setLoading(false) }
  }, [seasonId])
  useEffect(() => { requestId.current += 1; setData(null); setError(''); if (seasonId) void load() }, [seasonId, load])
  const groups = groupAssignments(data?.accounts || [])
  const awaiting = groups.find(group => !group.clanTag)?.accounts.length || 0
  const assignedGroups = groups.filter(group => group.clanTag).length
  return <div className="member-assignments">
    <div className="page-head"><div><h1>My clan assignments</h1><p>Your accounts, grouped by assigned clan.</p></div><label className="season-choice">Season<select value={seasonId} onChange={event => onSeasonChange(event.target.value)}><option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select></label></div>
    {!seasonId && <div className="card empty"><p>Select a season to check assignments.</p></div>}
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Retry</button></div>}
    {loading && <p role="status">Loading current assignments…</p>}
    {data && !loading && !error && <>
      {data.accounts.length > 0 && awaiting > 0 && <div className="card empty"><h2>{data.accounts.length} account{data.accounts.length === 1 ? ' is' : 's are'} signed up</h2><p>{assignedGroups ? 'Some accounts are waiting for the final roster.' : 'The roster is not final yet.'} We’ll notify you when it is published.</p><button onClick={() => void load()}>Refresh</button></div>}
      {assignedGroups > 0 && <div className="card member-compact-status"><div className="member-status-line"><strong>Published clan assignments</strong><button onClick={() => void load()}>Refresh</button></div></div>}
      {data.accounts.length ? <>
        <p className="member-assignment-count">{data.accounts.length} account{data.accounts.length === 1 ? '' : 's'} · {assignedGroups} hosting clan{assignedGroups === 1 ? '' : 's'}{awaiting ? ` · ${awaiting} awaiting placement` : ''}</p>
        <div className="member-clan-list">{groups.map((group, index) => <section className={`card member-clan-card ${group.clanTag ? '' : 'member-awaiting-card'}`} id={`member-clan-${index}`} key={group.key}><div className="member-clan-head"><div><h2>{group.clanName}</h2><small>{group.clanTag ? `${group.clanTag} · ${group.accounts.length} account${group.accounts.length === 1 ? '' : 's'}` : `${group.accounts.length} account${group.accounts.length === 1 ? '' : 's'} without a hosting clan`}</small></div>{group.clanTag && <a className="button member-open-clan" href={clanDeepLink(group.clanTag)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${group.clanName} in Clash of Clans`}><span>Open Clan</span><svg className="member-open-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M7 17 17 7M7 7h10v10" /></svg></a>}</div>{!group.clanTag && <p className="member-awaiting-note">Signed up · Waiting for the final roster.</p>}<div className="member-clan-rows">{group.accounts.map(account => <div className="member-clan-row" key={account.tag}><div><strong>{account.player_name}</strong><small>{account.tag}</small></div><span>TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main' : 'Lazy'}</span></div>)}</div></section>)}</div>
      </> : <div className="card empty"><h2>No accounts signed up yet</h2><p>Choose your linked accounts to sign up for this season.</p><a className="button primary" href={memberPath('signup',seasonId)}>Sign up →</a></div>}
    </>}
  </div>
}
