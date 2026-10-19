import { FilterPicker, leagueValue, matchesLeague, matchesTownHall } from './ClanFilters'
import { sortClans, clanSortOptions, type ClanSort } from './clanSort'
import { useEffect, useRef, useState } from 'react'
import { clanSummary, compareClanAccounts, comparisonOrder, moveComparisonClan } from './compare'
import { assignmentOptions, weightText, type RosterSnapshot, type RosterSort } from './roster'
import './CompareClans.css'
import type {Pool} from './api'
import { api } from './api'
import DiscordContact from './DiscordContact'
import { comparisonLocation, type ComparisonLocation } from './comparisonLocation'

type Props = { pool: Pool; seasonId: string; roster: RosterSnapshot; busy: boolean; onEdit: (tag: string) => void }
const sortOptions: { value: RosterSort; label: string }[] = [
  { value: 'town_hall_desc', label: 'Town Hall: high to low' }, { value: 'town_hall_asc', label: 'Town Hall: low to high' },
  { value: 'weight_desc', label: 'Weight: high to low' }, { value: 'weight_asc', label: 'Weight: low to high' }, { value: 'name', label: 'Name A–Z' },
]
const averageText = (value: number | null) => value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 1 })

export default function CompareClans({ pool, seasonId, roster, busy, onEdit }: Props) {
  const [locations, setLocations] = useState<Record<string, ComparisonLocation>>({})
  const [checking, setChecking] = useState(false)
  const [locationError, setLocationError] = useState('')
  const [refreshLocations, setRefreshLocations] = useState(0)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    setLocations({}); setChecking(true); setLocationError('')
    async function check(force = false) {
      try {
        const result = await api<{updating: boolean; accounts: (ComparisonLocation & {tag: string})[]}>(`/seasons/${encodeURIComponent(seasonId)}/arrival-check?background=1&source=draft${force ? '&refresh=1' : ''}`)
        if (cancelled) return
        setLocations(Object.fromEntries(result.accounts.map(account => [account.tag, account])))
        setChecking(result.updating); setNow(Date.now())
        if (result.updating) timer = setTimeout(() => void check(), 2000)
      } catch {
        if (!cancelled) { setChecking(false); setLocationError('Could not update locations. Try again.'); setLocations({}) }
      }
    }
    void check(true)
    const clock = setInterval(() => setNow(Date.now()), 30000)
    return () => { cancelled = true; clearTimeout(timer); clearInterval(clock) }
  }, [seasonId, refreshLocations])
  const [clanSort, setClanSort] = useState<ClanSort>('name')
  const [leagues,setLeagues] = useState<string[]>([])
  const [townHalls,setTownHalls] = useState<string[]>([])
  const allClans = sortClans(assignmentOptions(roster.clans).filter(clan=>clan.pool===pool), clanSort)
  const available = allClans.filter(clan=>matchesLeague(clan.cwl_league,leagues))
  const [clans, setClans] = useState<string[]>([])
  const [choosing, setChoosing] = useState(false)
  const [clanSearch, setClanSearch] = useState('')
  const loadedSeason = useRef<string | null>(null)
  const [sort, setSort] = useState<RosterSort>('town_hall_desc')
  const scroller = useRef<HTMLDivElement>(null)
  const activeTags = allClans.map(clan => clan.tag).sort().join('|')
  const visibleClans = clans.filter(tag => available.some(clan => clan.tag === tag))
  const matchingClans = available.filter(clan => `${clan.name} ${clan.tag}`.toLowerCase().includes(clanSearch.trim().toLowerCase()))
  useEffect(() => {
    const changedSeason = loadedSeason.current !== seasonId
    let saved: unknown = null
    if (changedSeason) {
      try { saved = JSON.parse(localStorage.getItem(`wu-compare-clans:${seasonId}:${pool}`) || 'null') } catch { /* Optional preference. */ }
      loadedSeason.current = seasonId
    }
    setClans(current => comparisonOrder(changedSeason ? saved : current, allClans.map(clan => clan.tag)))
  }, [seasonId, activeTags])
  const updateClans = (next: string[]) => {
    setClans(next)
    try { localStorage.setItem(`wu-compare-clans:${seasonId}:${pool}`, JSON.stringify(next)) } catch { /* Optional preference. */ }
  }
  const moveTo = (index: number) => {
    const container = scroller.current
    const column = container?.children[index] as HTMLElement | undefined
    if (container && column) container.scrollTo({ left: container.scrollLeft + column.getBoundingClientRect().left - container.getBoundingClientRect().left, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
  }
  return <section className="compare-workspace card" aria-labelledby="compare-title">
    <div className="card-heading"><div><p className="eyebrow">Staff placement</p><h2 id="compare-title">Compare clans</h2></div><label className="compare-sort">Sort players<select value={sort} onChange={event => setSort(event.target.value as RosterSort)}>{sortOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div>
    <p>Compare up to 10 {pool==='main'?'Main':'Lazy'} CWL clans side by side.</p>
    {roster.clans.some(clan=>!clan.archived&&!clan.pool)&&<p className="small">Some clans have no CWL group. Choose Main or Lazy in Clan settings to include them here.</p>}
    <div className="compare-location-controls"><small>Green: in this clan · Red: not in this clan · Gray: not checked</small><button disabled={checking} onClick={() => setRefreshLocations(value => value + 1)}>{checking ? 'Updating locations…' : 'Refresh clan locations'}</button>{locationError && <span role="alert">{locationError}</span>}</div>
    <div className="clan-filter-bar"><FilterPicker label="CWL leagues" options={[...new Set(sortClans(allClans,'league_desc').map(clan=>leagueValue(clan.cwl_league)))]} selected={leagues} onChange={setLeagues}/><FilterPicker label="Town Halls" options={[...new Set(roster.accounts.map(account=>account.town_hall))].sort((a,b)=>(b??-1)-(a??-1)).map(value=>value==null?'Unknown TH':`TH ${value}`)} selected={townHalls} onChange={setTownHalls}/><button disabled={!leagues.length&&!townHalls.length} onClick={()=>{setLeagues([]);setTownHalls([])}}>Clear filters</button><small>{available.length} of {allClans.length} clans match. Town Hall filters hide players only; clan totals stay unchanged.</small></div>
    {available.length === 0 ? <p className="inline-reason">No hosting clans match. Clear filters or add an active hosting clan in Seasons &amp; clans.</p> : <>
      <div className="compare-pan-controls">
        <button className="primary" aria-expanded={choosing} aria-controls="comparison-clan-picker" disabled={busy} onClick={() => setChoosing(!choosing)}>Choose clans · {clans.length}/10</button>
        <label>Sort chosen clans<select value="" disabled={busy} onChange={event => { const value=event.target.value as ClanSort; setClanSort(value); updateClans(sortClans(allClans.filter(clan=>clans.includes(clan.tag)),value).map(clan=>clan.tag)) }}><option value="" disabled>Choose order…</option>{clanSortOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      </div>
      {choosing && <div id="comparison-clan-picker" className="compare-picker">
        <label>Find a clan<input type="search" placeholder="Clan name or tag" value={clanSearch} onChange={event=>setClanSearch(event.target.value)} /></label>
        <p>Select up to 10 clans. New choices go on the right.</p>
        <div className="compare-picker-list">{matchingClans.map(clan=><label key={clan.tag}><input type="checkbox" checked={clans.includes(clan.tag)} disabled={busy || (!clans.includes(clan.tag) && clans.length>=10)} onChange={()=>updateClans(clans.includes(clan.tag)?clans.filter(tag=>tag!==clan.tag):[...clans,clan.tag])}/><span><strong>{clan.name}</strong><small>{clan.cwl_league || 'League unavailable'} · {clan.tag}</small></span></label>)}</div>
        {!matchingClans.length && <p>No clans match. Change the search or league filter.</p>}
        <div className="compare-picker-actions"><button disabled={busy || !clans.length} onClick={()=>updateClans([])}>Clear choices</button><button onClick={()=>setChoosing(false)}>Done</button></div>
      </div>}
      {visibleClans.length < clans.length && <p className="inline-reason">{clans.length-visibleClans.length} chosen clans are hidden by the league filter. Clear filters to show them.</p>}
      <div className="compare-jump" role="group" aria-label="Jump to comparison clan">{visibleClans.map((tag,index)=><button key={tag} onClick={()=>moveTo(index)}>{available.find(clan=>clan.tag===tag)?.name}</button>)}</div>
      {!visibleClans.length && <p className="inline-reason">Choose clans above to start comparing.</p>}
      <p id="compare-scroll-hint" className="compare-scroll-hint">↔ Swipe or scroll sideways here, or use the clan buttons above. Only this section moves.</p>
      <div className="compare-pan" ref={scroller} tabIndex={0} role="region" aria-label="Side-by-side clan comparison" aria-describedby="compare-scroll-hint" style={{ gridTemplateColumns: `repeat(${Math.max(1,visibleClans.length)}, minmax(280px, 1fr))` }}>
        {visibleClans.map((clanTag, index) => {
          const clan = available.find(item => item.tag === clanTag)
          const members = compareClanAccounts(roster.accounts, clanTag, sort).filter(account=>matchesTownHall(account.town_hall,townHalls))
          const summary = clanSummary(roster.accounts, clanTag)
          return <div className="compare-side" key={clanTag}>
            <div className="compare-column-tools"><button aria-label={`Move ${clan?.name} left`} disabled={busy || index===0} onClick={()=>updateClans(moveComparisonClan(clans,clanTag,visibleClans[index-1]))}>← Left</button><button aria-label={`Move ${clan?.name} right`} disabled={busy || index===visibleClans.length-1} onClick={()=>updateClans(moveComparisonClan(clans,clanTag,visibleClans[index+1]))}>Right →</button><button aria-label={`Remove ${clan?.name} from comparison`} disabled={busy} onClick={()=>updateClans(clans.filter(tag=>tag!==clanTag))}>✕</button></div>
            <label>Change clan<select value={clanTag} disabled={busy} onChange={event => { const destination = event.target.value; updateClans(clans.map(tag => tag===clanTag ? destination : tag===destination ? clanTag : tag)) }}>{available.map(item => <option value={item.tag} key={item.tag}>{item.name} · {item.cwl_league || 'League unavailable'} · {item.tag}</option>)}</select></label>
            {clan && <><div className="compare-clan-summary"><strong>{clan.name}</strong><small>🏆 {clan.cwl_league || 'League unavailable'}{clan.cwl_league_stale && clan.cwl_league ? ' · last known' : ''}</small><small>{summary.count}/{clan.effective_capacity} occupied</small><small>Avg TH {averageText(summary.averageTownHall)} ({summary.knownTownHalls} known)</small><small>Avg weight {summary.averageWeight === null ? '—' : weightText(summary.averageWeight)} ({summary.knownWeights} known)</small></div><div className="compare-player-list">{members.length ? members.map(account => {
              const location = comparisonLocation(locations[account.tag], clanTag, now)
              return <div key={account.tag} className={`compare-account compare-account-${location.state}`}><button type="button" disabled={busy} onClick={()=>onEdit(account.tag)} title={`Edit account · ${location.label} · ${location.detail}`} aria-label={`Edit ${account.player_name}: ${location.label}`} className={`compare-player compare-player-${location.state}`}><span className="compare-player-heading"><strong>{account.player_name}</strong><span>TH {account.town_hall ?? '—'}</span></span><small className="compare-player-meta">{account.tag} · {account.pool === 'main' ? 'Main' : 'Lazy'} · {weightText(account.effective_weight)}</small></button><div className="compare-contact"><DiscordContact userId={account.user_id} compact /></div></div>
            }) : <p>No accounts match in this clan.</p>}</div></>}
          </div>
        })}
      </div>
    </>}
  </section>
}
