import { useState } from 'react'
import DashboardIcon from '../DashboardIcon'
import { clanDeepLink } from '../publication'
import { countdown, localTime } from './calendar'
import { useClock } from './useClock'
import { useClanActivity, type War, type WarSide, type ClanActivity } from './useClanActivity'
import ClanActivityStatus from './ClanActivityStatus'
import './activity.css'

const labels: Record<string, string> = {none: 'No current war', private: 'Private war log', error: 'Unavailable', preparation: 'Preparation', inWar: 'Battle day', warEnded: 'Ended', awaitingResult: 'Awaiting final result'}
const inactive = new Set(['none', 'warEnded'])
function timing(war: War, now: number) {
  if (war.state === 'warEnded') return 'War ended'
  const time = war.state === 'preparation' ? war.starts_at : war.ends_at
  if (!time) return 'Timing unavailable'
  if (time * 1000 <= now) return 'Updating war state'
  return `${war.state === 'preparation' ? 'Starts' : 'Ends'} in ${countdown(time * 1000, now)}`
}
function Side({side}: {side: WarSide}) {
  return <div className="war-team">
    {side.badge_url?.startsWith('https://') && <img src={side.badge_url} alt="" width="36" height="36" loading="lazy"/>}
    <strong>{side.name}</strong>
    <small>{side.destruction == null ? 'Destruction unknown' : `${side.destruction.toFixed(1)}%`}</small>
  </div>
}
export function WarCard({clan, type, scope, now, onTasks}: {
  clan: ClanActivity; type: 'regular' | 'cwl'; scope: 'mine' | 'family'; now: number
  onTasks: (tag: string, kind: 'war' | 'cwl') => void
}) {
  const war = clan[type] || {state: 'error'}
  const accounts = war.my_accounts || []
  const matchup = war.clan && war.opponent
  return <article className="activity-card war-card" aria-label={`${clan.name} ${type === 'cwl' ? 'CWL' : 'war'}`}>
    <header className="war-card-meta">
      <span className="war-card-kind"><DashboardIcon name={type === 'cwl' ? 'trophy' : 'war'}/>{war.team_size ? `${war.team_size} vs ${war.team_size}` : type === 'cwl' ? 'CWL' : 'War'} <span className={`activity-state state-${war.state}`}>{labels[war.state] || 'Unknown'}</span></span>
      {matchup && <span>{timing(war, now)}</span>}
    </header>
    {matchup ? <>
      <div className="war-matchup"><Side side={war.clan!}/><div className="war-matchup-score" aria-label={`${war.clan!.stars ?? 'Unknown'} to ${war.opponent!.stars ?? 'unknown'} stars`}><strong>{war.clan!.stars ?? '—'} – {war.opponent!.stars ?? '—'}</strong><small>stars</small></div><Side side={war.opponent!}/></div>
      <div className="war-attacks"><span>{war.clan!.attacks ?? '—'} of {war.attacks_total ?? '—'} attacks</span><span>{war.opponent!.attacks ?? '—'} of {war.attacks_total ?? '—'} attacks</span></div>
    </> : <><h2>{clan.name}</h2><p>{war.state === 'private' ? 'This clan’s war log is private.' : war.state === 'error' ? 'Could not check this war. Refresh or check in-game.' : 'No current war.'}</p></>}
    {scope === 'mine' && <div className="war-personal">
      {accounts.length > 0 ? <><h3>Your accounts in this war</h3><ul>{accounts.map(account => <li key={account.tag}><span>{account.name}</span><strong>{account.attacks_left == null ? 'Attacks unknown' : war.state === 'warEnded' ? `${account.attacks_left} unused attacks` : `${account.attacks_left} of ${account.attacks_total ?? '—'} attacks left`}</strong></li>)}</ul>{clan.current_member === false && <small>CWL hosting clan · participating from another clan</small>}</> : <><h3>Your accounts in this clan</h3><p>{clan.accounts?.map(account => account.name).join(', ') || 'Account details unavailable'}</p>{matchup && <small>No linked accounts in this war lineup.</small>}</>}
    </div>}
    <details className="war-details"><summary>Details</summary>
      <div className="activity-dates"><div><small>Battle starts</small><span>{war.starts_at ? localTime(war.starts_at * 1000) : 'Unavailable'}</span></div><div><small>Battle ends</small><span>{war.ends_at ? localTime(war.ends_at * 1000) : 'Unavailable'}</span></div></div>
      <footer><a href={clanDeepLink(clan.tag)} target="_blank" rel="noopener noreferrer">Open clan ↗</a>{scope === 'mine' && <button className="war-text-action" onClick={() => onTasks(clan.tag, type === 'regular' ? 'war' : 'cwl')}>View my tasks →</button>}</footer>
      <small>{clan.tag}</small>
    </details>
  </article>
}
export default function WarsWorkspace({canEdit, onTasks, initialType = 'regular'}: {initialType?: 'regular' | 'cwl'; canEdit: boolean; onTasks: (tag: string, kind: 'war' | 'cwl') => void}) {
  const [chosenScope, setScope] = useState<'mine' | 'family'>('mine')
  const scope = canEdit ? chosenScope : 'mine'
  const [type, setType] = useState<'regular' | 'cwl'>(initialType)
  const [query, setQuery] = useState('')
  const {data, error, busy, refresh} = useClanActivity('war', scope)
  const now = useClock()
  const clans = (data?.clans || []).filter(clan => clan[type]?.state !== 'private' && (type === 'cwl' || scope === 'family' || clan.current_member !== false) && `${clan.name} ${clan.tag}`.toLowerCase().includes(query.toLowerCase().trim()))
  const active = clans.filter(clan => !inactive.has(clan[type]?.state || 'error'))
  const quiet = clans.filter(clan => inactive.has(clan[type]?.state || 'error'))
  const card = (clan: ClanActivity) => <WarCard key={clan.tag} {...{clan, type, scope, now, onTasks}}/>
  return <section className="clan-activity-workspace wars-workspace">
    <header className="page-head"><div><p className="eyebrow">Activity</p><h1>Wars</h1><p>{scope === 'mine' ? 'Your clans’ wars, scores, and your accounts’ remaining attacks.' : 'All family clans · war scores and battle times.'}</p></div></header>
    <div className="workflow-tabs" role="group" aria-label="War type">{(['regular', 'cwl'] as const).map(value => <button key={value} aria-pressed={type === value} onClick={() => setType(value)}><DashboardIcon name={value === 'regular' ? 'war' : 'trophy'}/>{value === 'regular' ? 'Clan wars' : 'CWL rounds'} {data && <small>{data.clans.filter(clan => ['inWar', 'preparation'].includes(clan[value]?.state || '')).length}</small>}</button>)}</div>
    <div className="activity-toolbar"><label>Find a clan<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Clan name or tag"/></label>{canEdit && <button aria-pressed={scope === 'family'} onClick={() => setScope(scope === 'mine' ? 'family' : 'mine')}>{scope === 'mine' ? 'Show all clans' : 'Show my clans'}</button>}</div>
    <ClanActivityStatus error={error} busy={busy} checkedAt={data?.checked_at} warnings={data?.warnings || []} refresh={refresh}/>
    {!data && busy && <p role="status">Loading your wars…</p>}
    {data && !clans.length && <p>{query ? 'No clans match this search.' : 'No wars to show. Private war logs are hidden.'}</p>}
    {data && clans.length > 0 && !active.length && <p>No active {type === 'cwl' ? 'CWL rounds' : 'wars'}{query ? ' match this search' : scope === 'mine' ? ' in your clans' : ''}.</p>}
    <div className="activity-card-grid">{active.map(card)}</div>
    {quiet.length > 0 && <details className="war-inactive"><summary>No active war · {quiet.length} {quiet.length === 1 ? 'clan' : 'clans'}</summary><div className="activity-card-grid">{quiet.map(card)}</div></details>}
    <p className="small">Refreshes every minute while visible. Game updates may take a little longer.</p>
  </section>
}
