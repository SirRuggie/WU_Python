import { useState } from 'react'
import DashboardIcon from '../DashboardIcon'
import { clanDeepLink } from '../publication'
import { countdown, localTime } from './calendar'
import { useClock } from './useClock'
import { useClanActivity, type War } from './useClanActivity'
import ClanActivityStatus from './ClanActivityStatus'
import './activity.css'

const labels: Record<string,string> = {none:'No current war',private:'Private war log',error:'Unavailable',preparation:'Preparation',inWar:'Battle day',warEnded:'Ended',awaitingResult:'Awaiting final result'}
function Score({war, now}: {war: War; now: number}) {
  if (!war.clan || !war.opponent) return <p>{war.state === 'private' ? 'This clan’s war log is private. Scores and attacks cannot be checked.' : war.state === 'error' ? 'Could not check this war. Retry or check in-game.' : 'No current war was returned for this clan.'}</p>
  const time = war.state === 'preparation' ? war.starts_at : war.ends_at
  return <>
    <p className="war-opponent">vs <strong>{war.opponent.name}</strong> <small>{war.team_size ? `${war.team_size} vs ${war.team_size}` : ''}</small></p>
    <div className="war-score" aria-label="Clan and opponent scores"><div><strong>{war.clan.stars ?? '—'} <small>stars</small></strong><span>{war.clan.destruction == null ? 'Destruction unknown' : `${war.clan.destruction.toFixed(1)}% destruction`}</span></div><span>—</span><div><strong>{war.opponent.stars ?? '—'} <small>stars</small></strong><span>{war.opponent.destruction == null ? 'Destruction unknown' : `${war.opponent.destruction.toFixed(1)}% destruction`}</span></div></div>
    <div className="war-attacks"><span>Clan attacks <b>{war.clan.attacks ?? '—'}/{war.attacks_total ?? '—'}</b></span><span>Opponent <b>{war.opponent.attacks ?? '—'}/{war.attacks_total ?? '—'}</b></span></div>
    {war.clan.attacks != null && war.attacks_total != null && war.attacks_total > 0 && <progress value={Math.min(war.clan.attacks,war.attacks_total)} max={war.attacks_total} aria-label="Clan attacks used"/>}
    <p className="activity-countdown">{time ? (time * 1000 <= now ? (war.state === 'warEnded' ? 'War ended' : 'Updating war state') : `${war.state === 'preparation' ? 'Starts' : 'Ends'} in ${countdown(time * 1000,now)}`) : 'Timing unavailable'}</p>
    <div className="activity-dates"><div><small>Battle starts</small><span>{war.starts_at ? localTime(war.starts_at * 1000) : 'Unavailable'}</span></div><div><small>Battle ends</small><span>{war.ends_at ? localTime(war.ends_at * 1000) : 'Unavailable'}</span></div></div>
  </>
}
export default function WarsWorkspace({canEdit,onTasks,initialType = 'regular'}: {initialType?: 'regular'|'cwl'; canEdit:boolean; onTasks:(tag:string,kind:'war'|'cwl')=>void}) {
  const [chosenScope,setScope] = useState<'mine'|'family'>('mine')
  const scope = canEdit ? chosenScope : 'mine'
  const [type,setType] = useState<'regular'|'cwl'>(initialType)
  const [query,setQuery] = useState('')
  const {data,error,busy,refresh} = useClanActivity('war',scope)
  const now = useClock()
  const clans = (data?.clans || []).filter(clan => `${clan.name} ${clan.tag}`.toLowerCase().includes(query.toLowerCase().trim()))
  return <section className="clan-activity-workspace">
    <header className="page-head"><div><p className="eyebrow">Activity · Clan overview</p><h1>Wars</h1><p>Full-clan scores, attack progress, and battle deadlines. Your own remaining attacks are in Tasks.</p></div></header>
    <div className="workflow-tabs" role="group" aria-label="War type"><button aria-pressed={type==='regular'} onClick={()=>setType('regular')}><DashboardIcon name="war"/> Clan wars {data && <small>{data.clans.filter(clan=>['inWar','preparation'].includes(clan.regular?.state || '')).length}</small>}</button><button aria-pressed={type==='cwl'} onClick={()=>setType('cwl')}><DashboardIcon name="trophy"/> CWL rounds {data && <small>{data.clans.filter(clan=>['inWar','preparation'].includes(clan.cwl?.state || '')).length}</small>}</button></div>
    <div className="activity-toolbar"><label>Find a clan<input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Clan name or tag"/></label>{canEdit && <label>Clans<select value={scope} onChange={event=>setScope(event.target.value as 'mine'|'family')}><option value="mine">My accounts’ clans</option><option value="family">Family clans</option></select></label>}</div>
    <ClanActivityStatus error={error} busy={busy} checkedAt={data?.checked_at} warnings={data?.warnings || []} refresh={refresh}/>
    {data && !clans.length && <p>{query ? 'No clans match this search.' : 'No clans found. Link an account that belongs to a clan, or choose the family directory if available.'}</p>}
    <div className="activity-card-grid">{clans.map(clan => {
      const war = clan[type] || {state:'error'}
      return <article className="activity-card" key={clan.tag}><header><div><h2>{clan.name}</h2><small>{clan.tag}</small></div><span className={`activity-state state-${war.state}`}>{labels[war.state] || 'Unknown'}</span></header><Score war={war} now={now}/><footer><a href={clanDeepLink(clan.tag)} target="_blank" rel="noopener noreferrer">Open clan ↗</a>{scope==='mine' && <button onClick={()=>onTasks(clan.tag,type==='regular'?'war':'cwl')}>My tasks in this clan</button>}</footer></article>
    })}</div>
    <p className="small">Refreshes every minute while visible. Game API caches can delay scores. Private or unavailable data is never counted as zero.</p>
  </section>
}
