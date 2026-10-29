import JoiningInstructionsCard from "./JoiningInstructionsCard";
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Season } from './api'
import { groupAssignments } from './assignmentGroups'
import { clanDeepLink, type MyAssignments } from './publication'
import './MemberAssignments.css'
import MemberSignupStatus from './MemberSignupStatus'
import { loadAccountDisplay } from './accountDisplay'
import type { Account } from './api'

type Props = { seasonId: string; seasons: Season[]; onSignup?: () => void; onChange?: () => void }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Assignments could not be loaded. Try again.'

export default function MemberAssignments({ seasonId, seasons, onSignup, onChange }: Props) {
  const [data, setData] = useState<MyAssignments | null>(null)
  const [linked, setLinked] = useState<Account[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const requestId = useRef(0)
  const activeSeason = useRef(seasonId)
  activeSeason.current = seasonId
  const load = useCallback(async (background = false) => {
    if (!seasonId || (background && inFlight.current)) return
    inFlight.current = true
    const sid = seasonId
    const id = ++requestId.current
    if (!background) setLoading(true)
    setError('')
    try {
      const result = await api<MyAssignments>(`/seasons/${encodeURIComponent(sid)}/my-assignments`)
      if (id === requestId.current && activeSeason.current === sid) setData(result)
    } catch (cause) { if (id === requestId.current && activeSeason.current === sid) setError(errorText(cause)) }
    finally { if (id === requestId.current) inFlight.current = false; if (id === requestId.current && activeSeason.current === sid) setLoading(false) }
  }, [seasonId])
  useEffect(() => { requestId.current += 1; setData(null); setError(''); if (seasonId) void load(); return () => { requestId.current += 1 } }, [seasonId, load])
  useEffect(() => {
    let active = true;
    setLinked(null);
    void loadAccountDisplay(() => {}, () => active).then(result => { if (active) setLinked(result.accounts) }).catch(() => {});
    return () => { active = false };
  }, [seasonId]);
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') void load(true) }
    const timer = window.setInterval(refresh, 30000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [load])
  const season = seasons.find(item => String(item.id) === seasonId)
  const groups = groupAssignments(data?.accounts || [])
  const awaiting = groups.find(group => !group.clanTag)?.accounts.length || 0
  const assignedGroups = groups.filter(group => group.clanTag).length
  return <div className="member-assignments">
    <div className="page-head"><div><h1>My clan assignments</h1><p>Your accounts, grouped by assigned clan.</p></div><p className="season-choice">{seasons.find(item => String(item.id) === seasonId)?.label || 'No CWL season available'}</p></div>
    {!seasonId && <div className="card empty"><p>Staff will make your CWL season available here.</p></div>}
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Retry</button></div>}
    {loading && <p role="status">Loading current assignments…</p>}
    {data && !loading && !error && <>
      {data.published?.joining_instructions && <JoiningInstructionsCard text={data.published.joining_instructions} />}
      <MemberSignupStatus signups={data.accounts} accounts={linked} season={season} published={!!data.published} onChange={onChange || (() => { window.location.href = '/my-signups' })} onRemaining={onSignup || (() => { window.location.href = '/signup' })} onRefresh={assignedGroups > 0 ? undefined : () => void load()} />
      {assignedGroups > 0 && <div className="card member-compact-status"><div className="member-status-line"><div><strong>Published clan assignments</strong>{data.published && <p>Version {data.published.version} · Published {new Date(data.published.published_at).toLocaleString()}</p>}</div><button onClick={() => void load()}>Refresh</button></div></div>}
      {data.accounts.length ? <>
        <p className="member-assignment-count">{data.accounts.length} account{data.accounts.length === 1 ? '' : 's'} · {assignedGroups} hosting clan{assignedGroups === 1 ? '' : 's'}{awaiting ? ` · ${awaiting} awaiting placement` : ''}</p>
        <div className="member-clan-list">{groups.filter(group => group.clanTag).map((group, index) => <section className={`card member-clan-card ${group.clanTag ? '' : 'member-awaiting-card'}`} id={`member-clan-${index}`} key={group.key}><div className="member-clan-head"><div><h2>{group.clanName}</h2><small>{group.clanTag ? `${group.clanTag} · ${group.accounts.length} account${group.accounts.length === 1 ? '' : 's'}` : `${group.accounts.length} account${group.accounts.length === 1 ? '' : 's'} without a hosting clan`}</small></div>{group.clanTag && <a className="button member-open-clan" href={clanDeepLink(group.clanTag)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${group.clanName} in Clash of Clans`}><span>Open Clan</span><svg className="member-open-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M7 17 17 7M7 7h10v10" /></svg></a>}</div>{!group.clanTag && <p className="member-awaiting-note">Signed up · Waiting for the final roster.</p>}<div className="member-clan-rows">{group.accounts.map(account => <div className="member-clan-row" key={account.tag}><div><strong>{account.player_name}</strong><small>{account.tag}</small></div><span>TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main' : 'Lazy'}</span></div>)}</div></section>)}</div>
      </> : null}
    </>}
  </div>
}
