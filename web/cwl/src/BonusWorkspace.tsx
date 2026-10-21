import useUnsavedWork from './useUnsavedWork'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Season } from './api'
import { PAGE_SIZE, pageItems, parseNullableWhole, selectionReasonError, selectionsChanged, selectionsFromAccounts, selectionsPayload, type BonusData, type BonusPolicy, type BonusPreview } from './bonus'
import './BonusWorkspace.css'

type Props = { seasonId: string; seasons: Season[]; onDirty?: (dirty: boolean) => void; onSeasonChange: (id: string) => void }
type Tab = 'review' | 'history' | 'rules'
type RuleDraft = { min_attacks: string; min_stars: string; cooldown_months: string; slots: Record<string, string> }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Bonus review could not be loaded. Try again.'
const display = (value: number | null) => value === null ? 'Unrecorded' : String(value)
const dateText = (value: string) => new Date(value).toLocaleString()
const ruleDraft = (data: BonusData): RuleDraft => ({ min_attacks: data.policy.min_attacks === null ? '' : String(data.policy.min_attacks), min_stars: data.policy.min_stars === null ? '' : String(data.policy.min_stars), cooldown_months: data.policy.cooldown_months === null ? '' : String(data.policy.cooldown_months), slots: Object.fromEntries(data.clans.map(clan => [clan.tag, clan.slots === null ? '' : String(clan.slots)])) })
const rulePayload = (draft: RuleDraft, data: BonusData): { policy: BonusPolicy; clans: { tag: string; slots: number | null }[] } | null => {
  const min_attacks = parseNullableWhole(draft.min_attacks, 0, 7)
  const min_stars = parseNullableWhole(draft.min_stars, 0, 21)
  const cooldown_months = parseNullableWhole(draft.cooldown_months, 0, 24)
  if (min_attacks === undefined || min_stars === undefined || cooldown_months === undefined) return null
  const clans = data.clans.map(clan => ({ tag: clan.tag, slots: parseNullableWhole(draft.slots[clan.tag] || '', 0, 50) }))
  if (clans.some(clan => clan.slots === undefined)) return null
  return { policy: { min_attacks, min_stars, cooldown_months }, clans: clans as { tag: string; slots: number | null }[] }
}

export default function BonusWorkspace({ seasonId, seasons, onSeasonChange, onDirty }: Props) {
  const [data, setData] = useState<BonusData | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [tab, setTab] = useState<Tab>('review')
  const [clanTag, setClanTag] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [historyPage, setHistoryPage] = useState(0)
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [rules, setRules] = useState<RuleDraft | null>(null)
  const [preview, setPreview] = useState<BonusPreview | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [voiding, setVoiding] = useState<{ id: number; reason: string } | null>(null)
  const requestId = useRef(0)
  const activeSeason = useRef(seasonId)
  activeSeason.current = seasonId
  const selectionDirty = data ? selectionsChanged(data.accounts, selected) : false
  const rulesDirty = !!(data && rules && JSON.stringify(rules) !== JSON.stringify(ruleDraft(data)))
  useUnsavedWork(selectionDirty || rulesDirty || !!voiding?.reason || busy, onDirty)
  const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived'
  const applyData = (next: BonusData, resetSelections = true, resetRules = true) => {
    setData(next)
    if (resetSelections) setSelected(selectionsFromAccounts(next.accounts))
    if (resetRules) setRules(ruleDraft(next))
    setClanTag(current => next.clans.some(clan => clan.tag === current) ? current : next.clans[0]?.tag || '')
  }
  const load = useCallback(async () => {
    if (!seasonId) return
    const sid = seasonId, id = ++requestId.current
    setLoading(true); setError('')
    try {
      const result = await api<BonusData>(`/seasons/${encodeURIComponent(sid)}/bonuses`)
      if (id === requestId.current && activeSeason.current === sid) {
        setData(result)
        setSelected(selectionsFromAccounts(result.accounts))
        setRules(ruleDraft(result))
        setClanTag(current => result.clans.some(clan => clan.tag === current) ? current : result.clans[0]?.tag || '')
        setPreview(null); setAcknowledged(false)
      }
    } catch (cause) { if (id === requestId.current && activeSeason.current === sid) setError(errorText(cause)) }
    finally { if (id === requestId.current && activeSeason.current === sid) setLoading(false) }
  }, [seasonId])
  useEffect(() => { requestId.current += 1; setData(null); setSelected({}); setRules(null); setPreview(null); setVoiding(null); setNotice(null); setError(''); setTab('review'); setClanTag(''); setSearch(''); setPage(0); setHistoryPage(0); if (seasonId) void load() }, [seasonId, load])
  const refresh = () => { if ((selectionDirty || rulesDirty) && !window.confirm('Discard unsaved bonus selections or rules and refresh?')) return; void load() }
  const changeSeason = (id: string) => { if ((selectionDirty || rulesDirty) && !window.confirm('Discard unsaved bonus selections or rules and change season?')) return; onSeasonChange(id) }
  const setSelection = (tag: string, checked: boolean) => { setSelected(current => { const next = { ...current }; if (checked) next[tag] = next[tag] || ''; else delete next[tag]; return next }); setPreview(null); setAcknowledged(false) }
  const setReason = (tag: string, reason: string) => { setSelected(current => ({ ...current, [tag]: reason })); setPreview(null); setAcknowledged(false) }
  const runMutation = async (action: () => Promise<BonusData>, success: string, resetSelections = true, resetRules = true) => {
    const sid = seasonId
    setBusy(true); setError(''); setNotice(null)
    try {
      const next = await action()
      if (activeSeason.current !== sid) return
      applyData(next, resetSelections, resetRules)
      setNotice({ kind: 'success', text: success })
      setPreview(null); setAcknowledged(false); setVoiding(null)
    } catch (cause) {
      if (activeSeason.current !== sid) return
      setError(cause instanceof ApiError && cause.status === 409 ? `${cause.message} Refresh and review the latest bonus draft.` : errorText(cause))
    } finally { setBusy(false) }
  }
  const saveDraft = () => {
    if (!data || busy || archived || !selectionDirty) return
    const reasonError = selectionReasonError(data.accounts, selected)
    if (reasonError) { setError(reasonError); return }
    void runMutation(() => api<BonusData>(`/seasons/${encodeURIComponent(seasonId)}/bonuses/draft`, 'PATCH', { revision: data.revision, selections: selectionsPayload(selected) }), 'Season-wide bonus draft saved. Review the server preview before confirming.', true, false)
  }
  const previewDraft = async () => {
    if (!data || busy || archived || selectionDirty) return
    const sid = seasonId
    setBusy(true); setError(''); setPreview(null); setAcknowledged(false)
    try {
      const result = await api<BonusPreview>(`/seasons/${encodeURIComponent(sid)}/bonuses/preview`)
      if (activeSeason.current === sid) setPreview(result)
    } catch (cause) { if (activeSeason.current === sid) setError(errorText(cause)) }
    finally { setBusy(false) }
  }
  const confirm = () => {
    if (!data || !preview || busy || archived || selectionDirty || !preview.can_confirm || rulesDirty || (preview.warnings.length > 0 && !acknowledged)) return
    void runMutation(() => api<BonusData>(`/seasons/${encodeURIComponent(seasonId)}/bonuses/confirm`, 'POST', { revision: preview.revision, fingerprint: preview.fingerprint, acknowledge_warnings: acknowledged }), 'Bonus selections confirmed in this dashboard. Award bonuses separately in Clash of Clans.', true, false)
  }
  const saveRules = () => {
    if (!data || !rules || busy || archived || !rulesDirty) return
    const parsed = rulePayload(rules, data)
    if (!parsed) { setError('Use whole numbers in the displayed ranges, or leave a rule unset.'); return }
    void runMutation(() => api<BonusData>(`/seasons/${encodeURIComponent(seasonId)}/bonuses/settings`, 'PATCH', { revision: data.revision, ...parsed }), 'Bonus review rules saved. Existing draft selections remain for review.', false, true)
  }
  const voidHistory = () => {
    if (!data || !voiding || busy || archived || !voiding.reason.trim() || voiding.reason.trim().length > 500) return
    const id = voiding.id, reason = voiding.reason.trim()
    void runMutation(() => api<BonusData>(`/seasons/${encodeURIComponent(seasonId)}/bonuses/${id}/void`, 'POST', { revision: data.revision, reason }), 'Recorded bonus selection voided. The history entry remains visible.', false, false)
  }
  const candidates = (data?.accounts || []).filter(account => account.assigned_clan_tag === clanTag && (!search.trim() || `${account.player_name} ${account.tag}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))).sort((a, b) => a.player_name.localeCompare(b.player_name) || a.tag.localeCompare(b.tag))
  const candidatePage = Math.min(page, Math.max(0, Math.ceil(candidates.length / PAGE_SIZE) - 1))
  const history = [...(data?.history || [])].sort((a, b) => b.confirmed_at.localeCompare(a.confirmed_at) || b.id - a.id)
  const maxHistoryPage = Math.max(0, Math.ceil(history.length / PAGE_SIZE) - 1)
  const selectedCount = Object.keys(selected).length
  const clan = data?.clans.find(item => item.tag === clanTag)
  const clanSelected = data?.accounts.filter(account => account.assigned_clan_tag === clanTag && selected[account.tag] !== undefined).length || 0
  const clanConfirmed = data?.cycle_confirmed.filter(item => item.clan_tag === clanTag).length || 0
  return <div className="bonus-workspace">
    <div className="page-head"><div><p className="eyebrow">Staff tools</p><h1>Bonus review &amp; history</h1><p>Choose bonus recipients here. Award bonuses separately in Clash of Clans.</p></div><label className="season-choice">Season<select value={seasonId} onChange={event => changeSeason(event.target.value)}><option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select></label></div>
    {!seasonId && <div className="card empty">Select a season to review bonuses.</div>}
    {error && <div className="notice error" role="alert">{error}<button onClick={refresh}>Refresh</button></div>}
    {notice && <div className={`notice ${notice.kind}`} role="status">{notice.text}</div>}
    {loading && <p role="status">Loading bonus review…</p>}
    {data && <>
      <div className="bonus-topline"><div><strong>{data.cycle ? `CWL ${data.cycle}` : 'CWL month not set'}</strong><small>{selectedCount} draft selection{selectedCount === 1 ? '' : 's'} · Revision {data.revision}</small></div><button disabled={busy || loading} onClick={refresh}>Refresh</button></div>
      {archived && <div className="notice">This season is archived. Bonus records are read-only.</div>}
      {!data.cycle && <p className="inline-reason">Choose a CWL month in Results &amp; participation before confirming selections.</p>}{data.active_other_cycles.length > 0 && <p className="inline-reason">This season has active dashboard bonus selections for {data.active_other_cycles.join(', ')}. Restore that CWL month or create a new season before confirming more.</p>}
      <div className="bonus-tabs" role="group" aria-label="Bonus sections"><button className={tab === 'review' ? 'active' : ''} aria-pressed={tab === 'review'} onClick={() => setTab('review')}>Review</button><button className={tab === 'history' ? 'active' : ''} aria-pressed={tab === 'history'} onClick={() => setTab('history')}>History</button><button className={tab === 'rules' ? 'active' : ''} aria-pressed={tab === 'rules'} onClick={() => setTab('rules')}>Rules</button></div>
      {tab === 'review' && <section className="bonus-review">
        <div className="bonus-review-controls"><label>Hosting clan<select value={clanTag} onChange={event => { setClanTag(event.target.value); setSearch(''); setPage(0); setPreview(null) }}><option value="">Select a clan</option>{data.clans.map(item => <option key={item.tag} value={item.tag}>{item.name} · {item.tag}</option>)}</select></label><label>Find account<input value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} placeholder="Name or tag" /></label></div>
        {clan && <div className="card bonus-clan-summary"><strong>{clan.name}</strong><span>{clanSelected} selected · {clanConfirmed} already recorded for this CWL month · {clan.slots === null ? 'Slots unset' : `${Math.max(0, clan.slots - clanConfirmed)} of ${clan.slots} slots remaining`}</span></div>}
        {data.accounts.length > 0 && <div className="bonus-review-actions"><button disabled={busy || archived || !selectionDirty} onClick={saveDraft}>Save selection draft</button><button className="primary" disabled={busy || archived || selectionDirty || rulesDirty || !selectedCount} onClick={() => void previewDraft()}>Review confirmation →</button></div>}
        {!data.clans.length && <div className="card empty">No hosting clans with published participants are available for bonus review.</div>}
        {clan && <><div className="bonus-candidate-list">{pageItems(candidates, candidatePage).map(account => <article key={account.tag} className="card bonus-candidate"><label className="bonus-candidate-check"><input type="checkbox" checked={selected[account.tag] !== undefined} disabled={busy || archived || (account.already_confirmed_this_cycle && selected[account.tag] === undefined)} onChange={event => setSelection(account.tag, event.target.checked)} /><span><strong>{account.player_name}</strong><small>{account.tag} · {account.pool === 'main' ? 'Main' : 'Lazy'} · Attacks {display(account.attacks)} · Stars {display(account.stars)}</small></span></label><div className="bonus-candidate-facts"><span>{account.already_confirmed_this_cycle ? 'Already confirmed this CWL month' : account.recommended === true ? 'Meets bonus rules' : account.recommended === false ? 'Outside bonus rules' : 'No recommendation yet'}</span><small>{account.eligibility_reason || 'Bonus rules or results are missing.'}</small><small>{account.last_confirmed_bonus ? `Last saved bonus selection: ${account.last_confirmed_bonus.cycle}` : account.already_confirmed_this_cycle ? 'Already confirmed this CWL month; see History' : 'No recorded bonus selection'}</small>{!account.source_complete && <small className="bonus-warning">Results are incomplete. Add a reason and review the warnings.</small>}{account.source_warning && <small className="bonus-warning">Source: {account.source_warning}</small>}{!account.source_warning && ['stale', 'unavailable', 'partial', 'preparation'].includes(account.source_status) && <small className="bonus-warning">Result source: {account.source_status}</small>}</div>{selected[account.tag] !== undefined && <label className="bonus-reason">Selection reason{account.recommended !== true || !account.source_complete || account.source_status !== 'complete' ? ' · required' : ' · optional'}<textarea rows={2} maxLength={500} value={selected[account.tag]} disabled={busy || archived} onChange={event => setReason(account.tag, event.target.value)} placeholder="Staff review note" /></label>}</article>)}</div>{!candidates.length && <div className="card empty">No accounts match this clan and search.</div>}{candidates.length > PAGE_SIZE && <div className="bonus-pages"><button disabled={candidatePage === 0} onClick={() => setPage(candidatePage - 1)}>Previous</button><span>Page {candidatePage + 1} of {Math.ceil(candidates.length / PAGE_SIZE)}</span><button disabled={candidatePage >= Math.ceil(candidates.length / PAGE_SIZE) - 1} onClick={() => setPage(candidatePage + 1)}>Next</button></div>}</>}
        {selectionDirty && <p className="inline-reason">Selections changed locally. Save the season-wide draft before requesting a confirmation preview.</p>}{rulesDirty && <p className="inline-reason">Save the rule changes before requesting a confirmation preview.</p>}
        {preview && <div className="card bonus-preview"><h2>Confirmation preview</h2><p>{preview.selected.length} selected account{preview.selected.length === 1 ? '' : 's'}. This saves your selection. Award bonuses separately in Clash of Clans.</p><div className="bonus-preview-list">{preview.selected.map(account => <div key={account.tag}><strong>{account.player_name}</strong><small>{account.assigned_clan_name || account.assigned_clan_tag} · {account.tag} · Attacks {display(account.attacks)} · Stars {display(account.stars)}</small></div>)}</div>{preview.capacity.map(row => <p className="small" key={row.clan_tag}>{row.clan_name}: {row.selected_count} selected · {row.confirmed_count} already recorded · {row.slots === null ? 'slots unset' : `${Math.max(0, row.slots - row.confirmed_count)} of ${row.slots} slots remaining before this selection`}</p>)}{preview.blocking_reasons.length > 0 && <div className="bonus-preview-blocks" role="alert"><strong>Confirmation is blocked</strong>{preview.blocking_reasons.map((reason, index) => <p key={index}>{reason}</p>)}</div>}{preview.warnings.length > 0 && <div className="bonus-preview-warnings"><strong>Review warnings</strong>{preview.warnings.map((warning, index) => <p key={index}>{warning}</p>)}<label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /> I reviewed these warnings and still want to record the selections.</label></div>}<button className="primary" disabled={busy || archived || !preview.can_confirm || rulesDirty || (preview.warnings.length > 0 && !acknowledged)} onClick={confirm}>Confirm selections</button>{!preview.can_confirm && <p className="inline-reason">Fix the issues above, save changes, then preview again.</p>}</div>}
      </section>}
      {tab === 'history' && <section className="bonus-history"><p className="small">Only selections saved here appear below. Older spreadsheet and in-game awards may be missing.</p>{history.length ? <><div className="bonus-history-list">{pageItems(history, Math.min(historyPage, maxHistoryPage)).map(item => <article className={`card bonus-history-row ${item.voided_at ? 'is-void' : ''}`} key={item.id}><div><strong>{item.player_name}</strong><small>{item.tag} · {item.clan_name || item.clan_tag || 'Unassigned'} · {item.cycle}</small><small>Attacks {display(item.attacks)} · Stars {display(item.stars)} · Published roster v{item.publication_version}</small><small>Confirmed {dateText(item.confirmed_at)} by Discord {item.confirmed_by}</small>{item.reason && <p>Reason: {item.reason}</p>}{item.warnings && item.warnings.length > 0 && <details><summary>Warnings recorded with this decision</summary>{item.warnings.map((warning, index) => <p className="bonus-warning" key={index}>{warning}</p>)}</details>}{item.voided_at && <p className="bonus-warning">Voided {dateText(item.voided_at)} by Discord {item.voided_by} · {item.void_reason}</p>}</div>{!item.voided_at && !archived && <button onClick={() => setVoiding({ id: item.id, reason: '' })}>Void record</button>}{voiding?.id === item.id && <div className="bonus-void"><label>Reason for voiding<textarea rows={2} maxLength={500} value={voiding.reason} onChange={event => setVoiding({ id: item.id, reason: event.target.value })} /></label><div><button onClick={() => setVoiding(null)}>Cancel</button><button className="primary" disabled={busy || !voiding.reason.trim()} onClick={voidHistory}>Confirm void</button></div></div>}</article>)}</div>{history.length > PAGE_SIZE && <div className="bonus-pages"><button disabled={historyPage === 0} onClick={() => setHistoryPage(historyPage - 1)}>Previous</button><span>Page {Math.min(historyPage, maxHistoryPage) + 1} of {maxHistoryPage + 1}</span><button disabled={historyPage >= maxHistoryPage} onClick={() => setHistoryPage(historyPage + 1)}>Next</button></div>}</> : <div className="card empty">No recorded bonus selections for this season.</div>}</section>}
      {tab === 'rules' && rules && <section className="card bonus-rules"><h2>Review rules</h2><p>Set all three rules to get recommendations. Blank means unknown; zero counts as a value. Set clan bonus slots before confirming selections.</p><div className="bonus-rule-fields"><label>Minimum attacks<input type="number" min="0" max="7" step="1" value={rules.min_attacks} disabled={archived || busy} onChange={event => setRules(current => current && ({ ...current, min_attacks: event.target.value }))} placeholder="Unset" /></label><label>Minimum stars<input type="number" min="0" max="21" step="1" value={rules.min_stars} disabled={archived || busy} onChange={event => setRules(current => current && ({ ...current, min_stars: event.target.value }))} placeholder="Unset" /></label><label>Cooldown months<input type="number" min="0" max="24" step="1" value={rules.cooldown_months} disabled={archived || busy} onChange={event => setRules(current => current && ({ ...current, cooldown_months: event.target.value }))} placeholder="Unset" /></label></div><h3>Clan bonus slots</h3><div className="bonus-slot-list">{data.clans.map(item => <label key={item.tag}>{item.name} · {item.tag}<input type="number" min="0" max="50" step="1" value={rules.slots[item.tag] || ''} disabled={archived || busy} onChange={event => setRules(current => current && ({ ...current, slots: { ...current.slots, [item.tag]: event.target.value } }))} placeholder="Unset" /></label>)}</div><button className="primary" disabled={busy || archived || !rulesDirty} onClick={saveRules}>Save rules</button>{rulesDirty && <p className="small">Save these rule changes before confirming bonus selections.</p>}</section>}
    </>}
  </div>
}
