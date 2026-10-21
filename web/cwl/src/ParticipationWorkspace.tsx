import useUnsavedWork from './useUnsavedWork'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Season } from './api'
import { canUseSyncedResults, parseOptionalCount, validCwlCycle, participationValidation, visibleParticipation, syncStatusLabel, type ParticipationAccount, type ParticipationData, type ParticipationSort, type ParticipationSync } from './participation'

type Props = { seasonId: string; seasons: Season[]; onDirty?: (dirty: boolean) => void; onSeasonChange: (id: string) => void }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Results could not be loaded. Try again.'
const dateText = (value: string) => new Date(value).toLocaleString()

function RecordCard({ account, publicationVersion, archived, onSave, onReset, onDirty }: { account: ParticipationAccount; publicationVersion: number | null; archived: boolean; onSave: (account: ParticipationAccount, revision: number, publicationVersion: number | null, sourceCheckedAt: string | null, attacks: number | null, stars: number | null, notes: string) => Promise<ParticipationAccount>; onReset: (account: ParticipationAccount) => Promise<ParticipationAccount>; onDirty: (tag: string, dirty: boolean) => void }) {
  const values = (row: ParticipationAccount) => ({ attacks: row.attacks === null ? '' : String(row.attacks), stars: row.stars === null ? '' : String(row.stars), notes: row.notes })
  const [draft, setDraft] = useState(() => values(account))
  const [base, setBase] = useState(() => ({ ...values(account), revision: account.revision, publicationVersion, sourceCheckedAt: account.source_checked_at ?? null }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const changed = draft.attacks !== base.attacks || draft.stars !== base.stars || draft.notes !== base.notes
  const latestValues = values(account)
  const stale = account.revision !== base.revision || publicationVersion !== base.publicationVersion || (account.source_checked_at ?? null) !== base.sourceCheckedAt || latestValues.attacks !== base.attacks || latestValues.stars !== base.stars || latestValues.notes !== base.notes
  useEffect(() => {
    if (changed || !stale) return
    const latest = values(account)
    setDraft(latest)
    setBase({ ...latest, revision: account.revision, publicationVersion, sourceCheckedAt: account.source_checked_at ?? null })
  }, [account, publicationVersion, changed, stale])
  useEffect(() => { onDirty(account.tag, changed || busy); return () => onDirty(account.tag, false) }, [account.tag, changed, busy, onDirty])
  const attackValue = parseOptionalCount(draft.attacks)
  const starValue = parseOptionalCount(draft.stars)
  const validation = attackValue === undefined || starValue === undefined ? 'Use whole numbers for attacks and stars, or leave them blank.' : participationValidation(attackValue, starValue, draft.notes)
  const useLatest = () => { const latest = values(account); setDraft(latest); setBase({ ...latest, revision: account.revision, publicationVersion, sourceCheckedAt: account.source_checked_at ?? null }); setError('') }
  const save = async () => {
    if (archived || !changed || stale || validation || attackValue === undefined || starValue === undefined) return
    setBusy(true); setError('')
    try {
      const saved = await onSave(account, base.revision, base.publicationVersion, base.sourceCheckedAt, attackValue, starValue, draft.notes)
      const latest = values(saved)
      setDraft(latest)
      setBase({ ...latest, revision: saved.revision, publicationVersion, sourceCheckedAt: saved.source_checked_at ?? null })
    } catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }
  const hasOverride = !!(account.attacks_override || account.stars_override)
  const hasSource = account.source_attacks !== null && account.source_attacks !== undefined || account.source_stars !== null && account.source_stars !== undefined
  const canReset = canUseSyncedResults(account)
  const reset = async () => {
    if (archived || busy || changed || stale || !canReset) return
    const partial = !account.source_complete ? ' These source results are partial and may change.' : ''
    if (!window.confirm(`Replace manual attack and star overrides for ${account.player_name} with the synced source values? Staff notes will remain.${partial}`)) return
    setBusy(true); setError('')
    try {
      const saved = await onReset(account)
      const latest = values(saved)
      setDraft(latest)
      setBase({ ...latest, revision: saved.revision, publicationVersion, sourceCheckedAt: saved.source_checked_at ?? null })
    } catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }
  return <article className="card participation-card">
    <div className="participation-card-head"><div><h3>{account.player_name}</h3><small>{account.tag} · TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main Clan CWL' : 'Lazy CWL'}</small><small>Hosting clan: {account.assigned_clan_name || account.assigned_clan_tag || 'Awaiting placement'}</small></div><span className="badge">{account.in_latest_publication ? 'Latest roster' : 'Saved history'}</span></div>
    {(account.roster_changed || !account.in_latest_publication) && <p className="inline-reason">{!account.in_latest_publication ? 'This account was removed from the published roster. Its saved results remain.' : 'The roster changed after these results were saved. Check the original account and clan before editing.'}{account.recorded_publication_version != null ? ` First recorded with version ${account.recorded_publication_version}.` : ''}</p>}
    {(account.source_warning || ['stale', 'unavailable'].includes(account.source_status || '')) && <p className="inline-reason">{account.source_warning || 'Source data is not freshly verified. Review before using results.'}</p>}
    <details className="participation-editor"><summary>Results &amp; notes · Attacks {draft.attacks || '—'} · Stars {draft.stars || '—'}{changed ? ' · Unsaved changes' : ''}{error ? ' · Save failed' : ''}</summary>
    <div className="participation-source"><strong>Synced CWL result</strong><span>Attacks {account.source_attacks ?? 'Unrecorded'} · Stars {account.source_stars ?? 'Unrecorded'}</span><small>{syncStatusLabel(account.source_status)}{hasSource ? account.source_complete ? ' · Final results' : ' · Partial results' : ''}{account.source_checked_at ? ` · Checked ${dateText(account.source_checked_at)}` : ''}</small>{account.source_warning && <small className="participation-error">{account.source_warning}</small>}{!account.source_warning && !account.source_complete && hasSource && <small className="participation-error">Source observations are incomplete; synced totals may change.</small>}{['stale', 'unavailable'].includes(account.source_status || '') && <small className="participation-error">Source data is not freshly verified. Review before using synced results.</small>}{hasOverride && <small>Manual correction in use{account.attacks_override && account.stars_override ? ' for attacks and stars' : account.attacks_override ? ' for attacks' : ' for stars'}.</small>}{hasOverride && <button disabled={archived || busy || changed || stale || !hasSource} onClick={() => void reset()}>Use synced results</button>}{hasOverride && !hasSource && <small>Synced values are unavailable, so the manual correction cannot be reset yet.</small>}{hasOverride && changed && <small>Save or discard your unsaved entry before using synced results.</small>}</div>
    <div className="participation-fields"><label>Current attacks<input type="number" min="0" max="7" step="1" inputMode="numeric" value={draft.attacks} disabled={archived || busy} onChange={event => setDraft(current => ({ ...current, attacks: event.target.value }))} placeholder="Unrecorded" /></label><label>Current stars<input type="number" min="0" max="21" step="1" inputMode="numeric" value={draft.stars} disabled={archived || busy} onChange={event => setDraft(current => ({ ...current, stars: event.target.value }))} placeholder="Unrecorded" /></label></div>
    <label className="participation-notes">Staff notes<textarea rows={3} maxLength={2000} value={draft.notes} disabled={archived || busy} onChange={event => setDraft(current => ({ ...current, notes: event.target.value }))} placeholder="Optional manual note" /></label>
    {stale && changed && <div className="inline-reason">This record or published roster changed while you were editing. Your unsaved entry is still here. Review the latest values before saving.<button onClick={useLatest} disabled={busy}>Discard entry and use latest values</button></div>}
    <div className="participation-card-foot"><div>{validation && changed && <small role="alert" className="participation-error">{validation}</small>}{error && <small role="alert" className="participation-error">{error}</small>}{account.updated_at && <small>Last saved {dateText(account.updated_at)}{account.updated_by ? ` by ${account.updated_by}` : ''}</small>}</div><button className="primary" disabled={archived || busy || !changed || stale || !!validation} onClick={() => void save()}>{busy ? 'Saving…' : 'Save record'}</button></div>
    </details>
  </article>
}

export default function ParticipationWorkspace({ seasonId, seasons, onSeasonChange, onDirty: reportDirty }: Props) {
  const [data, setData] = useState<ParticipationData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState<{ text: string; kind: 'success' | 'error' } | null>(null)
  const [dirtyTags, setDirtyTags] = useState<Set<string>>(new Set())
  const [syncDraft, setSyncDraft] = useState<{ cycle: string; enabled: boolean } | null>(null)
  const [syncDirty, setSyncDirty] = useState(false)
  const syncDirtyRef = useRef(false)
  syncDirtyRef.current = syncDirty
  const [syncBusy, setSyncBusy] = useState(false)
  const [syncError, setSyncError] = useState('')
  useUnsavedWork(dirtyTags.size > 0 || syncDirty || syncBusy, reportDirty)
  const onDirty = useCallback((tag: string, dirty: boolean) => setDirtyTags(current => { if (current.has(tag) === dirty) return current; const next = new Set(current); if (dirty) next.add(tag); else next.delete(tag); return next }), [])
  const changeSeason = (id: string) => { if ((dirtyTags.size || syncDirty) && !window.confirm(`Discard ${dirtyTags.size ? `unsaved manual results for ${dirtyTags.size} account${dirtyTags.size === 1 ? '' : 's'}` : 'unsaved sync settings'}?`)) return; setDirtyTags(new Set()); onSeasonChange(id) }
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [pool, setPool] = useState<'all' | 'main' | 'lazy'>('all')
  const [clan, setClan] = useState('all')
  const [sort, setSort] = useState<ParticipationSort>('name')
  const requestId = useRef(0)
  const currentSeason = useRef(seasonId)
  currentSeason.current = seasonId
  const load = useCallback(async () => {
    if (!seasonId) return
    const sid = seasonId, id = ++requestId.current
    setLoading(true); setError('')
    try {
      const result = await api<ParticipationData>(`/seasons/${encodeURIComponent(sid)}/participation`)
      if (id === requestId.current && currentSeason.current === sid) { setData(result); if (result.sync && !syncDirtyRef.current) setSyncDraft({ cycle: result.sync.cycle || '', enabled: result.sync.enabled }) }
    } catch (cause) { if (id === requestId.current && currentSeason.current === sid) setError(errorText(cause)) }
    finally { if (id === requestId.current && currentSeason.current === sid) setLoading(false) }
  }, [seasonId])
  useEffect(() => { requestId.current += 1; setData(null); setError(''); setNotice(null); setDirtyTags(new Set()); setSyncDraft(null); setSyncDirty(false); setSyncError(''); setSearch(''); setPool('all'); setClan('all'); setSort('name'); if (seasonId) void load() }, [seasonId, load])
  const saveSyncSettings = async () => {
    if (!seasonId || !syncDraft || syncBusy || archived || !validCwlCycle(syncDraft.cycle)) return
    const sid = seasonId
    const cycleChanged = syncDraft.cycle !== data?.sync?.cycle
    if (cycleChanged && dirtyTags.size && !window.confirm(`Changing the CWL month will discard unsaved result edits for ${dirtyTags.size} account${dirtyTags.size === 1 ? '' : 's'}. Continue?`)) return
    setSyncBusy(true); setSyncError('')
    try {
      const result = await api<{ sync: ParticipationSync }>(`/seasons/${encodeURIComponent(sid)}/participation/sync-settings`, 'POST', syncDraft)
      if (currentSeason.current !== sid) return
      setSyncDirty(false)
      syncDirtyRef.current = false
      if (cycleChanged) { setData(null); setDirtyTags(new Set()) }
      else setData(current => current ? { ...current, sync: result.sync } : current)
      await load()
      if (currentSeason.current === sid) setNotice({ kind: 'success', text: result.sync.enabled ? 'Automatic CWL results sync enabled.' : 'Automatic CWL results sync disabled. Sync now remains available.' })
    } catch (cause) { if (currentSeason.current === sid) setSyncError(errorText(cause)) }
    finally { setSyncBusy(false) }
  }
  const syncNow = async () => {
    if (!seasonId || syncBusy || archived || !data?.sync?.cycle || syncDirty) return
    const sid = seasonId
    setSyncBusy(true); setSyncError('')
    try {
      const result = await api<{ sync: ParticipationSync; updated_accounts: number }>(`/seasons/${encodeURIComponent(sid)}/participation/sync`, 'POST')
      if (currentSeason.current !== sid) return
      setNotice({ kind: 'success', text: `Sync checked the selected CWL month. ${result.updated_accounts} account${result.updated_accounts === 1 ? '' : 's'} updated.` })
    } catch (cause) { if (currentSeason.current === sid) setSyncError(errorText(cause)) }
    finally { if (currentSeason.current === sid) await load(); setSyncBusy(false) }
  }
  const resetToSource = async (account: ParticipationAccount): Promise<ParticipationAccount> => {
    const sid = seasonId
    try {
      const result = await api<{ account: ParticipationAccount }>(`/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}/reset-to-source`, 'POST', { revision: account.revision, publication_version: data?.publication_version, source_checked_at: account.source_checked_at ?? null })
      if (currentSeason.current === sid) {
        setData(current => current ? { ...current, accounts: current.accounts.map(row => row.tag === account.tag ? result.account : row) } : current)
        setNotice({ kind: 'success', text: `${account.player_name} now uses synced results. Staff notes were kept.` })
      }
      return result.account
    } catch (cause) {
      if (currentSeason.current === sid && cause instanceof ApiError && cause.status === 409) { setNotice({ kind: 'error', text: 'Source or roster changed. Latest records loaded; review before retrying.' }); await load() }
      throw cause
    }
  }
  const save = async (account: ParticipationAccount, revision: number, publicationVersion: number | null, sourceCheckedAt: string | null, attacks: number | null, stars: number | null, notes: string): Promise<ParticipationAccount> => {
    const sid = seasonId
    try {
      const result = await api<{ account: ParticipationAccount }>(`/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}`, 'PATCH', { revision, publication_version: publicationVersion, source_checked_at: sourceCheckedAt, attacks, stars, notes })
      if (currentSeason.current === sid) {
        setData(current => current ? { ...current, accounts: current.accounts.map(row => row.tag === account.tag ? result.account : row) } : current)
        setNotice({ kind: 'success', text: `${account.player_name} results saved.` })
      }
      return result.account
    } catch (cause) {
      if (currentSeason.current === sid && cause instanceof ApiError && cause.status === 409) {
        setNotice({ kind: 'error', text: 'This record or publication changed elsewhere. The latest records have been reloaded; review before saving again.' })
        await load()
      }
      throw cause
    }
  }
  const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived'
  const clans = [...new Map((data?.accounts || []).filter(account => account.assigned_clan_tag).map(account => [account.assigned_clan_tag!, account.assigned_clan_name || account.assigned_clan_tag!])).entries()].sort((a, b) => a[1].localeCompare(b[1]))
  const visible = visibleParticipation(data?.accounts || [], { search, pool, clan, sort })
  const lastPage = Math.max(0, Math.ceil(visible.length / 20) - 1)
  const currentPage = Math.min(page, lastPage)
  useEffect(() => setPage(0), [search, pool, clan, sort, seasonId])
  const visibleTags = new Set(visible.slice(currentPage * 20, (currentPage + 1) * 20).map(account => account.tag))
  const sorted = visibleParticipation(data?.accounts || [], { search: '', pool: 'all', clan: 'all', sort })
  return <div className="participation-workspace">
    <div className="page-head"><div><p className="eyebrow">Staff tools</p><h1>Results &amp; participation</h1><p>Review CWL results and add corrections or notes. Blank means unknown; zero is a saved result.</p></div><label className="season-choice">Season<select value={seasonId} onChange={event => changeSeason(event.target.value)}><option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select></label></div>
    {!seasonId && <div className="card empty"><p>Select a season to view its participation records.</p></div>}
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Retry</button></div>}
    {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}
    {loading && <p role="status">Loading manual results…</p>}
    {data && <>
      <section className="card participation-sync"><div className="card-heading"><div><p className="eyebrow">CWL result source</p><h2>Automatic results sync</h2></div><span className="badge">{syncStatusLabel(data.sync?.status)}</span></div><p>Choose a CWL month. Automatic checks run every 15 minutes and keep staff corrections and notes.</p><details><summary>Sync settings &amp; check history</summary><div className="participation-sync-fields"><label>CWL month<input type="month" value={syncDraft?.cycle || ''} disabled={archived || syncBusy} onChange={event => { setSyncDraft(current => ({ cycle: event.target.value, enabled: current?.enabled || false })); setSyncDirty(true) }} /></label><label className="participation-sync-toggle"><input type="checkbox" checked={syncDraft?.enabled || false} disabled={archived || syncBusy} onChange={event => { setSyncDraft(current => ({ cycle: current?.cycle || '', enabled: event.target.checked })); setSyncDirty(true) }} /><span>Check automatically every 15 minutes</span></label></div><div className="participation-sync-meta"><small>Selected source: {data.sync?.cycle_source === 'manage_binding' ? 'Manage CWL settings' : data.sync?.cycle_source === 'settings' ? 'Staff setting' : 'None'}</small><small>Last checked: {data.sync?.last_checked_at ? dateText(data.sync.last_checked_at) : 'Never'}</small><small>Last successful check: {data.sync?.last_success_at ? dateText(data.sync.last_success_at) : 'Never'}</small></div></details>{data.sync?.warning && <p className="inline-reason" role="alert">{data.sync.warning}</p>}{syncError && <p className="inline-reason" role="alert">{syncError}</p>}{archived && <p className="small">Archived seasons are read-only.</p>}<div className="participation-sync-actions"><button disabled={archived || syncBusy || !syncDirty || !validCwlCycle(syncDraft?.cycle || '')} onClick={() => void saveSyncSettings()}>{syncBusy ? 'Working…' : 'Save sync settings'}</button><button className="primary" disabled={archived || syncBusy || syncDirty || !data.sync?.cycle || data.publication_version === null} onClick={() => void syncNow()}>{syncBusy ? 'Checking…' : 'Sync now'}</button></div>{syncDirty && <p className="small">Save the selected month and automatic setting before syncing.</p>}{data.publication_version === null && <p className="small">Publish a roster before syncing results.</p>}</section>
      <div className="card participation-summary"><div><p className="eyebrow">CWL results</p><h2>{data.publication_version === null ? 'No published roster yet' : `Published roster · Version ${data.publication_version}`}</h2><p>{data.publication_version === null ? 'Publish a roster to begin recording participation.' : `${data.accounts.length} account${data.accounts.length === 1 ? '' : 's'} available. Records from an older publication remain visible if an account is later removed.`}</p></div><button onClick={() => void load()}>Refresh records</button></div>
      {archived && <div className="notice">This season is archived. Results are read-only.</div>}
      {data.accounts.length > 0 ? <><div className="card participation-filter"><label>Search account or clan<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, tag, or clan" /></label><label>Signup pool<select value={pool} onChange={event => setPool(event.target.value as typeof pool)}><option value="all">Both pools</option><option value="main">Main Clan CWL</option><option value="lazy">Lazy CWL</option></select></label><label>Hosting clan<select value={clan} onChange={event => setClan(event.target.value)}><option value="all">All hosting clans</option>{clans.map(([tag, name]) => <option key={tag} value={tag}>{name} · {tag}</option>)}</select></label><label>Sort<select value={sort} onChange={event => setSort(event.target.value as ParticipationSort)}><option value="name">Name A–Z</option><option value="attacks-desc">Attacks high to low</option><option value="attacks-asc">Attacks low to high</option><option value="stars-desc">Stars high to low</option><option value="stars-asc">Stars low to high</option><option value="th-desc">Town Hall high to low</option><option value="th-asc">Town Hall low to high</option></select></label></div><p className="small">Showing {visible.length ? currentPage * 20 + 1 : 0}–{Math.min((currentPage + 1) * 20, visible.length)} of {visible.length} matching accounts · Unknown values appear last.</p><div className="participation-grid">{sorted.map(account => <div key={`${seasonId}:${account.tag}`} hidden={!visibleTags.has(account.tag)}><RecordCard account={account} publicationVersion={data.publication_version} archived={!!archived} onSave={save} onReset={resetToSource} onDirty={onDirty} /></div>)}</div>{!visible.length && <div className="card empty"><p>No accounts match these filters.</p></div>}</> : <div className="card empty"><h2>No participation accounts yet</h2><p>{data.publication_version === null ? 'Publish a roster first. Signups and assignments do not count as results.' : 'The published roster has no accounts to record.'}</p></div>}
      {lastPage > 0 && <nav className="roster-pagination" aria-label="Participation pages"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage + 1} of {lastPage + 1}</span><button disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button></nav>}
    </>}
  </div>
}
