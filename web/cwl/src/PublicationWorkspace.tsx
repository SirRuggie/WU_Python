import { useDashboardPermission } from './DashboardPermissions'
import ClanRosterImages from './ClanRosterImages'
import CwlPoolTabs, {useCwlPool} from './CwlPoolTabs'
import StaffPlayerButton from './StaffPlayerButton'
import { readinessAccounts, type ReadinessFilter } from './readiness'
import ManageBridgeWorkspace from './ManageBridgeWorkspace'
import './publicationFlow.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Season } from './api'
import { draftPublicationStatus, type PublicationDraft, type PublicationMeta } from './publication'

type Props = { seasonId: string; seasons: Season[]; onSeasonChange: (id: string) => void; onFix: (filter: ReadinessFilter) => void; step: 'review' | 'announce'; onStepChange: (step: 'review' | 'announce') => void; onDirty?: (dirty: boolean) => void }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Publication request failed. Try again.'
const dateText = (value: string) => new Date(value).toLocaleString()

export default function PublicationWorkspace({ seasonId, seasons, onSeasonChange, onFix, step, onStepChange: setStep, onDirty }: Props) {
  const canManage = useDashboardPermission('cwl_publish')
  const [pool,setPool]=useCwlPool()
  const [imagesOpen, setImagesOpen] = useState(false)
  const [draft, setDraft] = useState<PublicationDraft | null>(null)
  const [rosterSearch, setRosterSearch] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const requestId = useRef(0)
  const currentSeason = useRef(seasonId)
  currentSeason.current = seasonId

  const load = useCallback(async () => {
    if (!seasonId) return
    const sid = seasonId
    const id = ++requestId.current
    setLoading(true); setError('')
    try {
      const result = await api<PublicationDraft>(`/seasons/${encodeURIComponent(sid)}/publication`)
      if (id !== requestId.current || currentSeason.current !== sid) return
      setDraft(result)
      setAcknowledged(false)
    } catch (cause) { if (id === requestId.current && currentSeason.current === sid) setError(errorText(cause)) }
    finally { if (id === requestId.current && currentSeason.current === sid) setLoading(false) }
  }, [seasonId])
  useEffect(() => {
    requestId.current += 1
    setDraft(null); setAcknowledged(false); setError(''); setSuccess(''); setRosterSearch('')
    if (seasonId) void load()
  }, [seasonId, load])

  const publish = async () => {
    if (!draft || !seasonId || busy || loading || error || archived || !draft.preview.accounts.length) return
    if (draft.preview.unassigned_count > 0 && !acknowledged) { setError('Acknowledge the unassigned accounts before publishing.'); return }
    const sid = seasonId
    setBusy(true); setError(''); setSuccess('')
    try {
      const result = await api<{ published: PublicationMeta }>(`/seasons/${encodeURIComponent(sid)}/publication`, 'POST', {
        revision: draft.draft_revision, acknowledge_unassigned: acknowledged, joining_instructions: draft.published?.joining_instructions || '',
      })
      if (currentSeason.current !== sid) return
      setDraft(current => current ? { ...current, draft_revision: result.published.revision + 1, draft_changed: false, published: result.published } : current)
      setAcknowledged(false)
      setStep('announce')
      setSuccess(`Version ${result.published.version} published. Members can now view these assignments.`)
      try { await load() } catch { /* load reports its own error */ }
    } catch (cause) {
      if (currentSeason.current === sid) {
        setError(cause instanceof ApiError && cause.status === 409 ? `${cause.message} Refresh the draft and review it before publishing.` : errorText(cause))
      }
    } finally { setBusy(false) }
  }
  const status = draft ? draftPublicationStatus(draft) : null
  const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived'
  const clans = new Map(draft?.preview.clans.map(clan => [clan.tag, clan.name]))
  const rosterGroups = new Map<string, { name: string; accounts: NonNullable<typeof draft>['preview']['accounts'] }>()
  for (const account of draft?.preview.accounts || []) {
    const hostingPool=draft?.preview.clans.find(c=>c.tag===account.assigned_clan_tag)?.pool || account.pool
    if(hostingPool!==pool)continue
    const key = account.assigned_clan_tag || 'unassigned'
    const name = account.assigned_clan_tag ? clans.get(account.assigned_clan_tag) || account.assigned_clan_tag : 'Awaiting placement'
    const group = rosterGroups.get(key) || { name, accounts: [] }
    group.accounts.push(account)
    rosterGroups.set(key, group)
  }
  const checks = (['unassigned', 'missing_weight', 'over_capacity'] as const).map(filter => ({ filter, accounts: draft ? readinessAccounts(draft.preview.accounts, draft.preview.clans, filter) : [] }))
  const labels = { unassigned: 'Unassigned accounts', missing_weight: 'Missing weights', over_capacity: 'Accounts in clans over capacity' }
  const query = rosterSearch.trim().toLowerCase()
  const visibleGroups = [...rosterGroups].map(([tag, group]) => ({
    tag, name: group.name, total: group.accounts.length,
    accounts: query ? group.accounts.filter(account =>
      [account.player_name, account.tag, account.pool, group.name, tag].some(value => value.toLowerCase().includes(query))
    ) : group.accounts,
  })).filter(group => group.accounts.length).sort((left, right) => {
    if (left.tag === 'unassigned') return 1
    if (right.tag === 'unassigned') return -1
    return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }) || left.tag.localeCompare(right.tag)
  })
  const visibleCount = visibleGroups.reduce((total, group) => total + group.accounts.length, 0)

  return <div className="publication-workspace">
    <div className="page-head"><div><p className="eyebrow">Staff tools</p><h1>{step === 'announce' ? 'Announcements' : 'Finalize roster'}</h1><p>{step === 'announce' ? 'Review the messages and send to Discord.' : 'Check the clans before making assignments visible.'}</p></div><label className="season-choice">Season<select value={seasonId} disabled={busy} onChange={event => onSeasonChange(event.target.value)}><option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select></label></div>
    {!seasonId && <div className="card empty"><p>Select a season to review its draft roster.</p></div>}
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Refresh draft</button></div>}
    {success && <div className="notice success" role="status">{success}<button type="button" onClick={() => setStep('announce')}>Continue to announcement</button></div>}
    {loading && <p role="status">Loading publication preview…</p>}
    <div hidden={step !== 'review'}>
      {draft && <>
        <section className="card publication-status"><div><p className="eyebrow">Member visibility</p><h2>{status === 'unpublished' ? 'Not published' : status === 'changed' ? 'Published roster has draft changes' : 'Published roster is current'}</h2><p>{status === 'unpublished' ? 'Assignments can change until the roster is published.' : status === 'changed' ? 'Publish again to make these changes official.' : 'Current placements match the official version.'}</p></div>{draft.published && <div className="publication-meta"><strong>Version {draft.published.version}</strong><span>Published {dateText(draft.published.published_at)}</span><span>{draft.published.assigned_count} assigned · {draft.published.unassigned_count} awaiting placement</span></div>}</section>
        <div className="roster-overview publication-totals"><div><strong>{draft.preview.accounts.length}</strong><span>draft accounts</span></div><div><strong>{draft.preview.assigned_count}</strong><span>assigned</span></div><div><strong>{draft.preview.unassigned_count}</strong><span>unassigned</span></div></div>
        <section className="card readiness-checks"><div className="card-heading"><div><p className="eyebrow">Roster readiness</p><h2>{checks.some(check => check.accounts.length) ? 'Review these items before publishing' : draft.preview.accounts.length ? 'Readiness checks passed' : 'Waiting for signups'}</h2><p>Missing weights do not block publishing. Confirm below if any accounts still need a clan.</p></div></div>{checks.map(check => <div className="staff-row" key={check.filter}><div><strong>{labels[check.filter]}</strong><small>{check.accounts.length} account{check.accounts.length === 1 ? '' : 's'}</small></div>{check.accounts.length > 0 ? <button disabled={busy || loading} onClick={() => onFix(check.filter)}>Review in roster builder →</button> : <span>✓ Clear</span>}</div>)}</section>
        <section className="card publication-form"><div className="card-heading"><div><p className="eyebrow">Step 1</p><h2>{draft.published ? 'Finalize updated roster' : 'Finalize roster'}</h2></div><button type="button" disabled={loading || busy} onClick={() => void load()}>Refresh draft</button></div><p>Review the clans below. Publishing makes this roster official.</p>{draft.preview.unassigned_count > 0 && <label className="publication-ack"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={event => setAcknowledged(event.target.checked)} /><span>I understand {draft.preview.unassigned_count} account{draft.preview.unassigned_count === 1 ? ' is' : 's are'} unassigned and will appear to members as awaiting placement.</span></label>}{archived && <p className="inline-reason">This season is archived. Its roster cannot be published or republished.</p>}{!draft.preview.accounts.length && <p className="inline-reason">No signed-up accounts are in this roster yet.</p>}<div className="publication-actions"><button className="primary" disabled={!canManage || busy || loading || !!error || archived || !draft.preview.accounts.length || (draft.preview.unassigned_count > 0 && !acknowledged)} onClick={() => void publish()}>{busy ? 'Finalizing…' : draft.published ? 'Finalize updated roster' : 'Finalize roster'}</button></div></section>
        <section className="card publication-preview"><div className="card-heading"><div><h2>Roster preview by clan</h2><p>{rosterGroups.size} placement group{rosterGroups.size === 1 ? '' : 's'} · expand a clan to check its accounts.</p></div></div><CwlPoolTabs value={pool} onChange={setPool} disabled={busy}/><label className="publication-search">Find an account or clan<input type="search" value={rosterSearch} onChange={event => setRosterSearch(event.target.value)} placeholder="Search name, tag, pool, or clan" /></label>{draft.preview.accounts.length ? <>{query && <p className="small">{visibleCount} matching account{visibleCount === 1 ? '' : 's'}</p>}{visibleGroups.length ? <div className="publication-groups">{visibleGroups.map(group => <details key={`${group.tag}:${query}`} className="publication-group" open={!!query}><summary><strong>{group.name}</strong><span>{group.tag === 'unassigned' ? '' : `${group.tag} · `}{query ? `${group.accounts.length} of ${group.total}` : group.total} account{group.total === 1 ? '' : 's'}</span></summary><div className="publication-list">{group.accounts.map(account => <div key={account.tag} className="publication-row"><div><StaffPlayerButton seasonId={seasonId} tag={account.tag} disabled={busy||archived} onChanged={load}>{account.player_name}</StaffPlayerButton><small>{account.tag} · TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main Clan CWL' : 'Lazy CWL'}</small></div><span className={account.assigned_clan_tag ? '' : 'publication-unassigned'}>{account.assigned_clan_tag ? group.name : 'Awaiting placement'}</span></div>)}</div></details>)}</div> : <p>No accounts in this group match this search.</p>}</> : <p>No signup accounts are in this draft roster.</p>}</section>
      </>}
    </div>
    {seasonId && step === 'announce' && <div><ManageBridgeWorkspace onDirty={onDirty} seasonId={seasonId} publicationVersion={draft?.published?.version ?? null} /><details className="card" onToggle={event => setImagesOpen(event.currentTarget.open)}><summary>Clan roster images &amp; testing</summary>{imagesOpen && <ClanRosterImages key={seasonId} seasonId={seasonId} version={draft?.published?.version??null}/>}</details></div>}
  </div>
}
