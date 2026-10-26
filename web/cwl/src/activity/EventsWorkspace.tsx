import { useState } from 'react'
import DashboardIcon from '../DashboardIcon'
import { clanDeepLink } from '../publication'
import { gameCalendar, countdown, localTime } from './calendar'
import { useClock } from './useClock'
import { useClanActivity } from './useClanActivity'
import ClanActivityStatus from './ClanActivityStatus'
import './activity.css'

export default function EventsWorkspace({canEdit,onWars}: {canEdit:boolean; onWars:()=>void}) {
  const now = useClock()
  const [utc,setUtc] = useState(false)
  const [chosenScope,setScope] = useState<'mine'|'family'>('mine')
  const scope = canEdit ? chosenScope : 'mine'
  const {data,error,busy,refresh} = useClanActivity('raid',scope)
  const zone = utc ? 'UTC' : undefined
  const zoneName = utc ? 'UTC' : Intl.DateTimeFormat().resolvedOptions().timeZone
  return <section className="clan-activity-workspace events-workspace">
    <header className="page-head"><div><p className="eyebrow">Activity · Game calendar</p><h1>Events</h1><p>What’s live and what’s next. Times shown in {zoneName}.</p></div><label className="activity-timezone"><input type="checkbox" checked={utc} onChange={event=>setUtc(event.target.checked)}/>Show UTC</label></header>
    <div className="activity-card-grid">{gameCalendar(now).map(event=>{
      const live = now >= event.start && now < event.end
      const signup = event.id === 'cwl'
      const target = live ? event.end : event.start
      return <article className={`activity-card calendar-card calendar-${event.id}`} key={event.id}>
        <header><div className="calendar-title"><span className="calendar-event-icon"><DashboardIcon name={event.icon}/></span><h2>{event.title}</h2></div><span className={`activity-state ${live?'state-inWar':''}`}>{live ? (signup?'Signup open':'Live') : 'Upcoming'}</span></header>
        <p className="calendar-countdown"><span>{live ? (signup?'Signup closes':'Ends') : (signup?'Signup opens':'Starts')} in</span><strong>{countdown(target,now)}</strong></p>
        <p className="calendar-description">{event.description}</p>
        {live && <progress value={Math.min(1,Math.max(0,(now-event.start)/(event.end-event.start)))} max={1} aria-label={`${event.title} time elapsed`}/>}
        <div className="activity-dates"><div><small>{signup?'Signup opens':'Starts'}</small><time dateTime={new Date(event.start).toISOString()}>{localTime(event.start,zone)}</time></div><div><small>{event.endLabel || 'Ends'}</small><time dateTime={new Date(event.end).toISOString()}>{localTime(event.end,zone)}</time></div></div>
        {signup && <button className="calendar-link" onClick={onWars}>View clan battle schedules →</button>}
      </article>
    })}</div>
    <details className="calendar-sources"><summary>About these dates</summary><p>These are the standard recurring game windows. Special events and maintenance can change them; the in-game timer takes precedence. CWL dates above cover signup only, not a fixed end date for every clan’s battles.</p><p>Schedule reviewed October 21, 2026. <a href="https://www.clash.ninja/guides/when-are-the-next-ingame-events" target="_blank" rel="noopener noreferrer">Clash Ninja schedule reference ↗</a> · <a href="https://supercell.com/en/games/clashofclans/blog/" target="_blank" rel="noopener noreferrer">Official event announcements ↗</a></p></details>
    <section className="clan-event-status" aria-labelledby="clan-raids-title"><div className="page-head"><div><h2 id="clan-raids-title">Clan raid activity</h2><p>Whole-clan progress from the game API. A scheduled weekend does not mean a clan has started raiding.</p></div>{canEdit && <label>Clans<select value={scope} onChange={event=>setScope(event.target.value as 'mine'|'family')}><option value="mine">My accounts’ clans</option><option value="family">Family clans</option></select></label>}</div>
      <ClanActivityStatus error={error} busy={busy} checkedAt={data?.checked_at} warnings={data?.warnings || []} refresh={refresh}/>
      {data && !data.clans.length && <p>No clans to show. Link an account in a clan to see its raid activity.</p>}
      <div className="activity-card-grid">{data?.clans.map(clan=>{
        const raid = clan.raid || {state:'error'}
        const expired = raid.ends_at != null && raid.ends_at * 1000 <= now
        return <article className="activity-card" key={clan.tag}><header><div><h3>{clan.name}</h3><small>{clan.tag}</small></div><span className="activity-state">{raid.state==='active'?(expired?'Awaiting update':'Raiding'):raid.state==='not_started'?'Not started':raid.state==='none'?'Between weekends':'Unavailable'}</span></header>
          {raid.state==='active' ? <><dl className="raid-totals"><div><dt>Attacks</dt><dd>{raid.attacks ?? '—'}</dd></div><div><dt>Districts cleared</dt><dd>{raid.districts ?? '—'}</dd></div><div><dt>Capital Gold</dt><dd>{raid.loot?.toLocaleString() ?? '—'}</dd></div></dl><div className="activity-dates"><div><small>Started</small><span>{raid.starts_at ? localTime(raid.starts_at*1000,zone) : 'Unavailable'}</span></div><div><small>Ends</small><span>{raid.ends_at ? localTime(raid.ends_at*1000,zone) : 'Unavailable'}</span></div></div></> : <p>{raid.state==='not_started'?'No active raid was returned for this clan yet.':raid.state==='none'?'The next standard raid window is shown above.':'Could not check this clan’s raid activity. This does not mean it has not started.'}</p>}
          <footer><a href={clanDeepLink(clan.tag)} target="_blank" rel="noopener noreferrer">Open clan ↗</a></footer>
        </article>
      })}</div>
    </section>
  </section>
}
