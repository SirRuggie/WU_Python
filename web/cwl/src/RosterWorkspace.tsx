import ClanDestinationOptions from './ClanDestinationOptions'
import CwlPoolTabs, {useCwlPool} from './CwlPoolTabs'
import RosterPlayerDialog from './RosterPlayerDialog'
import DiscordContact from './DiscordContact'
import TownHallIcon from './TownHallIcon'
import './RosterWorkspace.css'
import { FilterPicker, leagueValue, matchesLeague, matchesTownHall } from './ClanFilters'
import {sortClans} from './clanSort'
import WeightQueue from './WeightQueue'
import { readinessAccounts, type ReadinessFilter } from './readiness'
import CompareClans from './CompareClans'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type Pool, type Season } from './api'
import { assignmentOptions, filterRosterAccounts, sortRosterAccounts, parseManualWeightK, parseWeightK, weightInputText, weightText, type AutoPreview, type RosterAccount, type RosterClan, type RosterSnapshot, type RosterSort } from './roster'

type Props = { seasonId: string; seasons: Season[]; onSeasonChange: (id: string) => void; initialReadiness?: ReadinessFilter; onReviewPublication?: () => void }
type Feedback = { kind: 'success' | 'error'; text: string }
const poolName = (pool: Pool | null) => pool === 'lazy' ? 'Lazy CWL' : pool === 'main' ? 'Main Clan CWL' : 'Pool not set'
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The roster request failed. Try again.'
const statusText = (status: RosterAccount['source_status']) => status === 'current' ? 'Current' : status === 'unavailable' ? 'Source unavailable; prior value may be stale' : 'Missing weight'
const encoded = (value: string) => encodeURIComponent(value)

export default function RosterWorkspace({ seasonId, seasons, onSeasonChange, initialReadiness = 'all', onReviewPublication }: Props) {
  const [editingTag,setEditingTag] = useState<string|null>(null)
  const [roster, setRoster] = useState<RosterSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [preview, setPreview] = useState<AutoPreview | null>(null)
  const [mode,setMode] = useState<'assign'|'compare'|'rules'|'weights'>('assign')
  const [page,setPage] = useState(0)
  const [manualTag,setManualTag] = useState<string|null>(null)
  const [manualClan,setManualClan] = useState('')
  const [ruleTag, setRuleTag] = useState('')
  const [leagues,setLeagues] = useState<string[]>([])
  const [townHalls,setTownHalls] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [readinessFilter, setReadinessFilter] = useState<ReadinessFilter>(initialReadiness)
  const [poolFilter, setPoolFilter] = useCwlPool()
  const [assignmentFilter, setAssignmentFilter] = useState<'all' | 'assigned' | 'unassigned'>('all')
  const [sort, setSort] = useState<RosterSort>('name')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [bulkDestination, setBulkDestination] = useState('')
  const [weightEdit, setWeightEdit] = useState<{ tag: string; value: string } | null>(null)
  const listHeading = useRef<HTMLDivElement>(null)
  const requestId = useRef(0)
  const activeSeason = useRef(seasonId)
  activeSeason.current = seasonId

  const refresh = useCallback(async () => {
    if (!seasonId) return null
    const id = ++requestId.current
    const snapshot = await api<RosterSnapshot>(`/seasons/${encoded(seasonId)}/roster`)
    if (id !== requestId.current || activeSeason.current !== seasonId) return null
    setRoster(snapshot)
    return snapshot
  }, [seasonId])
  useEffect(() => {
    setEditingTag(null); setMode('assign'); setPage(0); setManualTag(null); setRoster(null); setPreview(null); setWeightEdit(null); setFeedback(null); setSelectedTags([]); setBulkDestination('')
    if (!seasonId) return
    setLoading(true)
    void refresh().catch(error => setFeedback({ kind: 'error', text: errorText(error) })).finally(() => { if (activeSeason.current === seasonId) setLoading(false) })
  }, [seasonId, refresh])

  const afterWrite = async (success: string) => {
    setPreview(null)
    try { await refresh(); setFeedback({ kind: 'success', text: success }) }
    catch (error) { setFeedback({ kind: 'error', text: `${success} The latest roster could not be loaded: ${errorText(error)}` }) }
  }
  const fail = async (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) {
      try { await refresh() } catch { /* Original conflict remains the useful error. */ }
      setPreview(null)
      setFeedback({ kind: 'error', text: `${error.message} The roster was refreshed; review it and try again.` })
    } else setFeedback({ kind: 'error', text: errorText(error) })
  }
  const edit = async (tag: string, body: Record<string, unknown>, success: string): Promise<boolean> => {
    if (!roster || !seasonId || busy) return false
    const sid = seasonId
    setBusy(true); setFeedback(null)
    try {
      await api(`/seasons/${encoded(sid)}/roster/${encoded(tag)}`, 'PATCH', { revision: roster.revision, ...body })
      if (activeSeason.current === sid) await afterWrite(success)
      return true
    } catch (error) { if (activeSeason.current === sid) await fail(error); return false }
    finally { setBusy(false) }
  }
  const removeSignup = async (tag: string): Promise<boolean> => {
    if (!roster || !seasonId || busy) return false
    const sid=seasonId
    setBusy(true);setFeedback(null)
    try {
      await api(`/seasons/${encoded(sid)}/staff-signups/${encoded(tag)}`, 'DELETE', {revision:roster.revision})
      if(activeSeason.current===sid){setSelectedTags(tags=>tags.filter(value=>value!==tag));await afterWrite('Signup removed. Publish again to update the published roster.')}
      return true
    } catch(error){if(activeSeason.current===sid)await fail(error);return false}
    finally{setBusy(false)}
  }
  const saveRules = async (clan: RosterClan, rules: { pool: Pool; capacity: number; min_weight: number | null; max_weight: number | null; lower_league: boolean | null }) => {
    if (!roster || !seasonId || busy) return
    const sid = seasonId
    setBusy(true); setFeedback(null)
    try {
      await api(`/seasons/${encoded(sid)}/lineup/${encoded(clan.tag)}/rules`, 'PATCH', { revision: roster.revision, ...rules })
      if (activeSeason.current === sid) await afterWrite(`${clan.name} placement rules saved.`)
    } catch (error) { if (activeSeason.current === sid) await fail(error) }
    finally { setBusy(false) }
  }
  const saveWeight = async (account: RosterAccount) => {
    if (!weightEdit || weightEdit.tag !== account.tag) return
    let weight: number | null
    try { weight = parseManualWeightK(weightEdit.value) }
    catch (error) { setFeedback({ kind: 'error', text: errorText(error) }); return }
    const saved = await edit(account.tag, { manual_weight: weight }, weight === null ? 'Manual weight cleared; source weight restored.' : 'Weight saved for this and future seasons.')
    if (saved) setWeightEdit(null)
  }
  const previewPlacement = async () => {
    if (!roster || !seasonId || busy) return
    const sid = seasonId
    setBusy(true); setFeedback(null); setPreview(null)
    try {
      const result = await api<AutoPreview>(`/seasons/${encoded(sid)}/roster/auto-preview`, 'POST', { revision: roster.revision, pool: poolFilter })
      if (activeSeason.current === sid) setPreview(result)
    } catch (error) { if (activeSeason.current === sid) await fail(error) }
    finally { setBusy(false) }
  }
  const applyPlacement = async () => {
    if (!preview || !roster || !seasonId || busy || preview.revision !== roster.revision) return
    const sid = seasonId
    setBusy(true); setFeedback(null)
    try {
      const result = await api<{ revision: number; applied: number }>(`/seasons/${encoded(sid)}/roster/auto-apply`, 'POST', { revision: preview.revision, pool: poolFilter, placements: preview.placements })
      if (activeSeason.current === sid) await afterWrite(`${result.applied} account${result.applied === 1 ? '' : 's'} placed from the reviewed preview.`)
    } catch (error) { if (activeSeason.current === sid) await fail(error) }
    finally { setBusy(false) }
  }
  const refreshWeights = async () => {
    if (!roster || !seasonId || busy) return
    const sid = seasonId
    setBusy(true); setFeedback(null)
    try {
      const result = await api<{ revision: number; refreshed: number; missing: number }>(`/seasons/${encoded(sid)}/roster/refresh-weights`, 'POST', { revision: roster.revision })
      if (activeSeason.current === sid) await afterWrite(`Weight refresh finished: ${result.refreshed} refreshed, ${result.missing} missing.`)
    } catch (error) {
      if (activeSeason.current === sid) {
        try { await refresh() } catch { /* Preserve source error. */ }
        await fail(error)
      }
    } finally { setBusy(false) }
  }
  const filtered = roster ? sortRosterAccounts(filterRosterAccounts(readinessAccounts(roster.accounts, roster.clans, readinessFilter), search, poolFilter, assignmentFilter).filter(account=>matchesTownHall(account.town_hall,townHalls) && (!leagues.length || (!!account.assigned_clan_tag && matchesLeague(roster.clans.find(clan=>clan.tag===account.assigned_clan_tag)?.cwl_league,leagues)))), sort) : []
  const lastPage = Math.max(0, Math.ceil(filtered.length / 20) - 1)
  const currentPage = Math.min(page,lastPage)
  const pageAccounts = filtered.slice(currentPage*20,(currentPage+1)*20)
  useEffect(()=>{setPage(0);setSelectedTags([]);setManualTag(null)},[search,poolFilter,assignmentFilter,readinessFilter,leagues,townHalls])
  const visibleTags = pageAccounts.map(account => account.tag)
  const allVisibleSelected = visibleTags.length > 0 && visibleTags.every(tag => selectedTags.includes(tag))
  const toggleSelected = (tag: string) => setSelectedTags(current => current.includes(tag) ? current.filter(item => item !== tag) : [...current, tag])
  const bulkAssign = async () => {
    if (!roster || !seasonId || busy || !selectedTags.length) return
    if (selectedTags.length > 50) { setFeedback({ kind: 'error', text: 'Select up to 50 accounts per bulk assignment.' }); return }
    if (bulkDestination && bulkDestination !== '__unassign__' && !assignmentOptions(roster.clans).some(clan => clan.tag === bulkDestination)) { setFeedback({ kind: 'error', text: 'Choose an active hosting clan.' }); return }
    if (!bulkDestination) { setFeedback({ kind: 'error', text: 'Choose a hosting clan or Unassign selected.' }); return }
    const sid = seasonId
    setBusy(true); setFeedback(null)
    try {
      const result = await api<{ revision: number; updated: number }>(`/seasons/${encoded(sid)}/roster/assignments`, 'PATCH', { revision: roster.revision, tags: selectedTags, assigned_clan_tag: bulkDestination === '__unassign__' ? null : bulkDestination })
      if (activeSeason.current === sid) { setSelectedTags([]); await afterWrite(`${result.updated} account${result.updated === 1 ? '' : 's'} ${bulkDestination === '__unassign__' ? 'unassigned' : 'assigned to ' + clanName(bulkDestination)}.`) }
    } catch (error) { if (activeSeason.current === sid) await fail(error) }
    finally { setBusy(false) }
  }
  const undoPlacement = async () => {
    if (!roster?.undo || !seasonId || busy) return
    const sid = seasonId
    setBusy(true); setFeedback(null)
    try {
      await api(`/seasons/${encoded(sid)}/roster/undo`, 'POST', { revision: roster.revision, undo_id: roster.undo.id })
      if (activeSeason.current === sid) await afterWrite('Last placement change undone.')
    } catch (error) {
      if (activeSeason.current === sid) {
        if (!(error instanceof ApiError && error.status === 409)) { try { await refresh() } catch { /* Keep original error. */ } }
        await fail(error)
      }
    } finally { setBusy(false) }
  }
  const poolAccounts = roster?.accounts.filter(account=>account.pool===poolFilter) || []
  const assigned = poolAccounts.filter(account => !!account.assigned_clan_tag).length || 0
  const missingWeight = poolAccounts.filter(account => account.effective_weight === null).length || 0
  const activeClans = roster?.clans.filter(clan => !clan.archived && (clan.pool===poolFilter || !clan.pool)) || []
  const ruleClan = activeClans.find(clan => clan.tag === ruleTag) || activeClans[0]
  const clanName = (tag: string | null) => roster?.clans.find(clan => clan.tag === tag)?.name || tag || 'Unassigned'

  return <div className="roster-workspace">
    <div className="page-head"><div><p className="eyebrow">Staff roster</p><h1>Roster builder</h1><p>Select accounts, choose a hosting clan, and assign. Changes save immediately.</p></div><label className="season-choice">Season<select value={seasonId} onChange={event => onSeasonChange(event.target.value)}><option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select></label></div>
    {!seasonId && <div className="card empty"><p>Select a season to build its CWL roster.</p></div>}
    {feedback && <div className={`notice ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.text}<button aria-label="Dismiss message" onClick={() => setFeedback(null)}>×</button></div>}
    {loading && <p role="status">Loading roster…</p>}
    {roster && <>
      <CwlPoolTabs value={poolFilter} disabled={busy} onChange={pool=>{setPoolFilter(pool);setPreview(null);setBulkDestination('');setRuleTag('');setLeagues([]);setTownHalls([]);setSearch('');setEditingTag(null)}}/>
      <div className="roster-overview"><div><strong>{poolAccounts.length}</strong><span>signed-up accounts</span></div><div><strong>{assigned}</strong><span>assigned</span></div><div><strong>{poolAccounts.length - assigned}</strong><span>unassigned</span></div><div><strong>{missingWeight}</strong><span>missing effective weight</span></div></div>
      <div className="roster-workflow-nav" role="group" aria-label="Roster workspace views">{([{id:'assign',label:'Assign accounts'},{id:'compare',label:'Compare clans'},{id:'rules',label:'Clan settings'},{id:'weights',label:`Weights · ${missingWeight} missing`}] as const).map(item=><button key={item.id} disabled={busy} aria-pressed={mode===item.id} className={mode===item.id?'active':''} onClick={()=>{setMode(item.id);setManualTag(null);setSelectedTags([]);setWeightEdit(null)}}>{item.label}</button>)}</div>
      <div className="roster-toolbar"><span>{mode==='assign'?'1. Find accounts → 2. Select → 3. Assign a clan':mode==='compare'?'Compare up to 10 clans side by side.':mode==='rules'?'Set clan capacity and automatic placement ranges.':'Check missing weights and manage overrides.'}</span><button disabled={busy} onClick={()=>void refresh().catch(error=>setFeedback({kind:'error',text:errorText(error)}))}>Refresh</button>{mode==='assign'&&<button disabled={busy||!activeClans.length} onClick={()=>void previewPlacement()}>Auto-place preview</button>}{onReviewPublication&&<button className="primary" disabled={busy} onClick={onReviewPublication}>Finalize both groups →</button>}</div>
      {mode==='weights'&&<WeightQueue onEdit={tag=>{setFeedback(null);setEditingTag(tag)}} key={seasonId} accounts={poolAccounts} busy={busy} onRefresh={()=>void refreshWeights()} onClose={()=>setMode('assign')} onSave={(tag,weight)=>edit(tag,{manual_weight:weight},'Manual weight saved. Existing placement preserved.')}/>}
      {roster.undo && <div className="roster-undo card"><div><strong>Undo last placement change</strong><small>{roster.undo.label}</small></div><button disabled={busy || roster.undo.revision !== roster.revision} onClick={() => void undoPlacement()}>Undo</button></div>}
      {mode==='rules' && <section id="clan-range-editor" className="roster-rules card"><div className="card-heading"><h2>Clan ranges & capacity</h2></div><p>Set this season’s weight range and capacity. Automatic placement uses these settings. Existing assignments stay unchanged.</p>{ruleClan ? <><label>Hosting clan<select value={ruleClan.tag} onChange={event => setRuleTag(event.target.value)} disabled={busy}>{activeClans.map(clan => <option key={clan.tag} value={clan.tag}>{clan.name} · {clan.cwl_league || 'League unavailable'} · {clan.tag}</option>)}</select></label><RuleForm key={`${seasonId}-${ruleClan.tag}-${roster.revision}`} clan={ruleClan} busy={busy} onSave={rules => void saveRules(ruleClan, rules)} /></> : <p>Add a hosting clan in Seasons & clans first.</p>}</section>}
      {editingTag&&roster.accounts.some(a=>a.tag===editingTag)&&<RosterPlayerDialog key={`${seasonId}:${editingTag}`} account={roster.accounts.find(a=>a.tag===editingTag)!} clans={roster.clans} busy={busy} error={feedback?.kind==='error'?feedback.text:undefined} onClose={()=>{if(!busy)setEditingTag(null)}} onSave={body=>edit(editingTag,body,'Account updated.')} onRemove={()=>removeSignup(editingTag)}/>}
      {mode==='compare'&&<CompareClans key={`${seasonId}:${poolFilter}`} pool={poolFilter} seasonId={seasonId} roster={roster} busy={busy} onEdit={tag=>{setFeedback(null);setEditingTag(tag)}} />}
      {mode==='assign'&&preview && <section className="card roster-preview" aria-labelledby="preview-title"><div className="card-heading"><h2 id="preview-title">Automatic placement preview</h2><button onClick={() => setPreview(null)}>Close preview</button></div><p>{preview.placements.length} proposed placement{preview.placements.length === 1 ? '' : 's'} · {preview.unassigned.length} unresolved. Nothing changes until you apply this preview.</p><div className="preview-columns"><div><h3>Proposed placements</h3><div className="preview-scroll">{preview.placements.length ? preview.placements.map(item => <div className="preview-line" key={item.tag}><strong>{roster.accounts.find(account => account.tag === item.tag)?.player_name || item.tag}</strong><small>{item.tag} → {clanName(item.assigned_clan_tag)}</small></div>) : <p>No accounts can be placed with the current rules.</p>}</div></div><div><h3>Accounts still needing a clan</h3><div className="preview-scroll">{preview.unassigned.length ? preview.unassigned.map(item => <div className="preview-line" key={item.tag}><strong>{roster.accounts.find(account => account.tag === item.tag)?.player_name || item.tag}</strong><small>{item.tag} · {roster.accounts.find(account=>account.tag===item.tag)?.auto_placement_note || reasonText(item.reason)}</small></div>) : <p>None.</p>}</div></div></div><div className="roster-preview-actions"><button className="primary" disabled={busy || !preview.placements.length || preview.revision !== roster.revision} onClick={() => void applyPlacement()}>Apply reviewed placements</button></div></section>}
      {mode==='assign'&&<>
      <div className="roster-placement-overview"><strong>{poolAccounts.filter(account=>account.auto_placement_reason==='ready').length} ready for auto-placement · {poolAccounts.filter(account=>account.auto_placement_reason&&account.auto_placement_reason!=='ready').length} need attention</strong><p>Automatic placement follows capacity, weights and signup pools. Choose Place manually to assign an account yourself.</p><button onClick={()=>setMode('rules')}>Review clan settings</button><button onClick={()=>setMode('weights')}>Review missing weights</button></div>
      <div className="roster-quick-search"><label>Find accounts<input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Name, tag or Discord ID"/></label><label>Show<select value={assignmentFilter} onChange={event=>setAssignmentFilter(event.target.value as 'all'|'assigned'|'unassigned')}><option value="all">All accounts</option><option value="unassigned">Unassigned</option><option value="assigned">Assigned</option></select></label><label>Sort<select value={sort} onChange={event=>setSort(event.target.value as RosterSort)}><option value="name">Name A–Z</option><option value="town_hall_desc">TH: highest first</option><option value="town_hall_asc">TH: lowest first</option><option value="weight_desc">Weight: highest first</option><option value="weight_asc">Weight: lowest first</option></select></label></div>
      <details className="roster-more-filters"><summary>Filters · League &amp; Town Hall {readinessFilter!=='all'||leagues.length||townHalls.length?'· Active':''}</summary>
      <div className="card readiness-filter"><label>Readiness check<select value={readinessFilter} onChange={event => { setReadinessFilter(event.target.value as ReadinessFilter); setSelectedTags([]) }}><option value="all">All accounts</option><option value="unassigned">Unassigned accounts</option><option value="missing_weight">Missing weights</option><option value="over_capacity">Clans over capacity</option></select></label></div>
      <div className="clan-filter-bar"><FilterPicker label="Assigned clan league" options={[...new Set(sortClans(roster.clans,'league_desc').map(clan=>leagueValue(clan.cwl_league)))]} selected={leagues} onChange={values=>{setLeagues(values);setSelectedTags([])}}/><FilterPicker label="Town Halls" options={[...new Set(roster.accounts.map(account=>account.town_hall))].sort((a,b)=>(b??-1)-(a??-1)).map(value=>value==null?'Unknown TH':`TH ${value}`)} selected={townHalls} onChange={values=>{setTownHalls(values);setSelectedTags([])}}/><button onClick={()=>{setLeagues([]);setTownHalls([]);setSearch('');setAssignmentFilter('all');setReadinessFilter('all');setSelectedTags([])}}>Clear filters</button><small>{filtered.length} of {poolAccounts.length} accounts shown. League filters use the assigned clan; unassigned accounts have no league.</small></div>
      </details><div className="roster-list-heading" ref={listHeading}><label className="roster-select-all"><input type="checkbox" checked={allVisibleSelected} disabled={busy || !visibleTags.length} onChange={event => setSelectedTags(event.target.checked ? [...new Set([...selectedTags,...visibleTags])].slice(0,50) : selectedTags.filter(tag=>!visibleTags.includes(tag)))} /> Select all {visibleTags.length} on this page</label><span>{filtered.length} matching · {selectedTags.length} selected</span></div>
      {filtered.length ? <div className="roster-account-list">{pageAccounts.map(account => <article className={`card roster-account ${account.assigned_clan_tag?'roster-account-assigned':''} ${selectedTags.includes(account.tag)?'roster-account-selected':''}`} key={account.tag}><div className="roster-account-head"><label className="roster-account-select"><input type="checkbox" aria-label={`Select ${account.player_name} for bulk assignment`} checked={selectedTags.includes(account.tag)} disabled={busy || (!selectedTags.includes(account.tag) && selectedTags.length>=50)} onChange={() => toggleSelected(account.tag)} /></label><div><h3><button className="roster-player-name" disabled={busy} onClick={()=>{setFeedback(null);setEditingTag(account.tag)}} aria-label={`Edit ${account.player_name}`}><TownHallIcon level={account.town_hall}/>{account.player_name}</button></h3><small>{account.tag} · TH {account.town_hall ?? '—'}</small><DiscordContact userId={account.user_id}/></div><span className="badge">{poolName(account.pool)}</span></div><div className="roster-row-summary"><span><small>Weight</small><strong>{weightText(account.effective_weight)}</strong></span><span><small>Hosting clan</small><strong>{clanName(account.assigned_clan_tag)}</strong></span><span className="roster-current-clan"><small>Current clan{account.current_clan_status === 'stale' ? ' · Last checked' : ''}</small><strong>{account.current_clan_status === 'unavailable' || !account.current_clan_status ? 'Unavailable' : account.current_clan_name || account.current_clan_tag || 'No clan'}</strong></span><span>{account.kept ? '🔒 Kept' : account.assigned_clan_tag ? '✓ Assigned' : account.auto_placement_reason==='ready' ? 'Ready to auto-place' : 'Not assigned'}</span></div><div className="roster-placement-help"><button disabled={busy} onClick={()=>{setFeedback(null);setEditingTag(account.tag)}}>Edit account</button>{!account.assigned_clan_tag&&<small>{account.auto_placement_note || 'Choose a hosting clan to place this account.'}</small>}<button disabled={busy} onClick={()=>{setManualTag(account.tag);setManualClan(account.assigned_clan_tag||'');setFeedback(null)}}>{account.assigned_clan_tag?'Move account':'Place manually'}</button></div>{manualTag===account.tag&&<form className="roster-manual-place" onSubmit={event=>{event.preventDefault();if(!manualClan)return;void edit(account.tag,{assigned_clan_tag:manualClan,kept:true},`${account.player_name} assigned to ${clanName(manualClan)}.`).then(saved=>{if(saved)setManualTag(null)})}}><label>Place {account.player_name} in<select autoFocus value={manualClan} disabled={busy} onChange={event=>setManualClan(event.target.value)}><option value="">Choose a hosting clan</option><ClanDestinationOptions clans={roster.clans} current={account.assigned_clan_tag}/></select></label><p>Staff can choose any active clan with space, including a different Main or Lazy group.</p>{feedback?.kind==='error'&&<p role="alert">{feedback.text}</p>}<button type="submit" className="primary" disabled={busy||!manualClan}>{busy?'Saving…':'Save placement'}</button><button type="button" disabled={busy} onClick={()=>setManualTag(null)}>Cancel</button></form>}<details className="roster-account-details"><summary>Account details &amp; changes</summary><small>{account.user_id ? `Discord ID: ${account.user_id}` : 'No Discord account'}</small><div className="roster-data"><div><small>Source weight</small><strong>{weightText(account.source_weight)}</strong><small>{statusText(account.source_status)}{account.source_name ? ` · ${account.source_name}` : ''}{account.source_modified_at ? ` · Source updated ${new Date(account.source_modified_at).toLocaleString()}` : ''}{account.source_checked_at ? ` · Fetched ${new Date(account.source_checked_at).toLocaleString()}` : ''}</small></div><div><small>Weight used</small><strong>{weightText(account.effective_weight)}</strong><small>{account.manual_weight === null ? 'Using imported weight' : `Manual override: ${weightText(account.manual_weight)}`}</small>{account.initial_manual_weight != null && <small>First saved weight: {weightText(account.initial_manual_weight)}</small>}</div><div><small>Hosting clan</small><strong>{clanName(account.assigned_clan_tag)}{roster.clans.find(clan => clan.tag === account.assigned_clan_tag)?.archived ? ' · Archived' : ''}</strong><small>{account.kept ? 'Kept placement' : 'Available for auto-placement'}</small></div></div><div className="roster-controls"><label>Assign hosting clan<select value={account.assigned_clan_tag || ''} disabled={busy} onChange={event => void edit(account.tag, { assigned_clan_tag: event.target.value || null, kept: true }, event.target.value ? 'Hosting clan assignment saved.' : 'Account unassigned and kept.') }><option value="">Unassigned</option>{account.assigned_clan_tag && roster.clans.find(clan => clan.tag === account.assigned_clan_tag)?.archived && <option value={account.assigned_clan_tag} disabled>{clanName(account.assigned_clan_tag)} · Archived (current)</option>}<ClanDestinationOptions clans={roster.clans} current={account.assigned_clan_tag}/></select></label><button disabled={busy} onClick={() => void edit(account.tag, { kept: !account.kept }, account.kept ? 'Account released for automatic placement.' : 'Placement kept.')}>{account.kept ? 'Release keep' : 'Keep placement'}</button><button disabled={busy} onClick={() => { setWeightEdit({ tag: account.tag, value: weightInputText(account.manual_weight ?? account.effective_weight) }); setFeedback(null) }}>Edit weight</button>{account.manual_weight !== null && <button disabled={busy} onClick={() => void edit(account.tag, { manual_weight: null }, 'Source weight restored.')}>Restore source</button>}</div>{weightEdit?.tag === account.tag && <div className="weight-editor"><label>Manual FWA weight (k)<small>Saved for future seasons. Previous weights stay in history.</small><input type="number" inputMode="decimal" min="0" step="0.001" value={weightEdit.value} onChange={event => setWeightEdit({ tag: account.tag, value: event.target.value })} placeholder="Leave blank to use source" /></label><button className="primary" disabled={busy} onClick={() => void saveWeight(account)}>Save weight</button><button onClick={() => setWeightEdit(null)}>Cancel</button></div>}</details></article>)}</div> : <div className="card empty"><p>No accounts match these filters.</p></div>}
      {filtered.length>20&&<nav className="roster-pagination" aria-label="Account pages"><button disabled={busy||currentPage===0} onClick={()=>{setPage(currentPage-1);listHeading.current?.scrollIntoView({block:'start'})}}>← Previous</button><span>Page {currentPage+1} of {lastPage+1}</span><button disabled={busy||currentPage===lastPage} onClick={()=>{setPage(currentPage+1);listHeading.current?.scrollIntoView({block:'start'})}}>Next →</button></nav>}
      {selectedTags.length>0&&<div className="roster-bulk card roster-selection-bar"><strong>{selectedTags.length}/50 selected</strong><label>Hosting clan<select value={bulkDestination} disabled={busy} onChange={event => setBulkDestination(event.target.value)}><option value="">Choose a destination</option><option value="__unassign__">Unassign selected</option><ClanDestinationOptions clans={roster.clans}/></select></label><button className="primary" disabled={busy || !selectedTags.length || selectedTags.length > 50 || !bulkDestination} onClick={() => void bulkAssign()}>{bulkDestination === '__unassign__' ? 'Unassign selected' : 'Assign selected'}</button>{selectedTags.length > 50 && <small role="alert">Select up to 50 accounts per request.</small>}<button disabled={busy} onClick={()=>setSelectedTags([])}>Clear selection</button></div>}
      </>}
    </>}
  </div>
}
function reasonText(reason: string) {
  const labels: Record<string, string> = { kept: 'Kept placement', missing_weight: 'Missing weight', source_unavailable: 'Weight source unavailable', no_eligible_rule: 'No matching hosting rule', full: 'Matching clans are full' }
  return labels[reason] || reason.replaceAll('_', ' ')
}
function RuleForm({ clan, busy, onSave }: { clan: RosterClan; busy: boolean; onSave: (rules: { pool: Pool; capacity: number; min_weight: number | null; max_weight: number | null; lower_league: boolean | null }) => void }) {
  const [pool, setPool] = useState<Pool | ''>(clan.pool ?? '')
  const [capacity, setCapacity] = useState(clan.capacity === null ? '' : String(clan.capacity))
  const [minWeight, setMinWeight] = useState(weightInputText(clan.min_weight))
  const [maxWeight, setMaxWeight] = useState(weightInputText(clan.max_weight))
  const [error, setError] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    try {
      const min = parseWeightK(minWeight)
      const max = parseWeightK(maxWeight)
      if (min !== null && max !== null && min >= max) throw new Error('Maximum weight must be greater than minimum weight.')
      const size = Number(capacity)
      if (!pool) throw new Error('Choose a signup pool for this hosting clan.')
      if (capacity === '' || (size !== 15 && size !== 30)) throw new Error('Capacity must be 15 or 30.')
      setError('')
      onSave({ pool, capacity: size, min_weight: min, max_weight: max, lower_league: clan.lower_league })
    } catch (error) { setError(errorText(error)) }
  }
  return <form className="roster-rule-form" onSubmit={submit}><div className="card-heading"><h3>{clan.name}</h3><span className="badge">{clan.assigned_count}/{clan.capacity ?? '—'} assigned</span></div><small>{clan.tag}</small><div className="rule-fields"><label>Signup pool<select value={pool} onChange={event => setPool(event.target.value as Pool)}><option value="">Not set</option><option value="main">Main Clan CWL</option><option value="lazy">Lazy CWL</option></select></label><label>Capacity<select value={capacity} onChange={event => setCapacity(event.target.value)}><option value="">Not set</option><option value="15">15</option><option value="30">30</option></select></label><label>Minimum weight (k, included)<input type="number" min="0" step="0.001" value={minWeight} onChange={event => setMinWeight(event.target.value)} placeholder="No minimum" /></label><label>Maximum weight (k, excluded)<input type="number" min="0" step="0.001" value={maxWeight} onChange={event => setMaxWeight(event.target.value)} placeholder="No maximum" /></label></div><p className="small">Enter weights in thousands: 160 means 160,000. Leave either end blank for no limit. The maximum is excluded, so 160–174 includes 160k up to just below 174k.</p>{error && <p className="inline-reason" role="alert">{error}</p>}<button className="primary" disabled={busy}>Save clan range & rules</button></form>
}
