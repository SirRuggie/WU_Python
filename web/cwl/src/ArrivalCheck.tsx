import {useCallback, useEffect, useRef, useState} from 'react'
import CwlPoolTabs, {useCwlPool} from './CwlPoolTabs'
import StaffPlayerButton from './StaffPlayerButton'
import DiscordContact from './DiscordContact'
import {api} from './api'
import TownHallIcon from './TownHallIcon'
import {normalizeArrivalAccount, summarizeArrivalReadiness} from './arrivalReadiness'
import './ArrivalCheck.css'

type Account = {
  hosting_pool: 'main' | 'lazy'; pool: 'main' | 'lazy'; tag: string
  user_id?: string | null; player_name: string; town_hall: number | null
  assigned_clan_tag: string | null; assigned_clan_name: string | null
  current_clan_tag: string | null; current_clan_name: string | null
  current_clan_checked_at?: string; location_updating?: boolean
  arrival_status: 'arrived' | 'missing' | 'unknown' | 'unassigned'; outside_family: boolean
}
type Result = {
  publication_available: boolean; publication_outdated: boolean; published_at: string | null
  removed_since_publication: number; added_since_publication: number; updating?: boolean
  source: 'published' | 'draft'; version: number | null; accounts: Account[]
}
type Props = {seasonId: string; onDirty?: (dirty: boolean) => void; onBusy?: (busy: boolean) => void}

export default function ArrivalCheck({seasonId, onDirty, onBusy}: Props) {
  const [data, setData] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [source, setSource] = useState('draft')
  const [onlyMissing, setOnlyMissing] = useState(false)
  const [search, setSearch] = useState('')
  const [pool, setPool] = useCwlPool()
  const [now, setNow] = useState(Date.now())
  const [editDirty, setEditDirty] = useState(false)
  const [editBusy, setEditBusy] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const generation = useRef(0)
  const reportDirty = useCallback((dirty: boolean) => {setEditDirty(dirty); onDirty?.(dirty)}, [onDirty])
  useEffect(() => {onBusy?.(editBusy); return () => onBusy?.(false)}, [editBusy, onBusy])
  useEffect(() => () => onDirty?.(false), [onDirty])
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000)
    return () => window.clearInterval(timer)
  }, [])

  async function load(refresh = false) {
    const id = ++generation.current
    setBusy(true)
    setError('')
    try {
      const result = await api<Result>(`/seasons/${encodeURIComponent(seasonId)}/arrival-check?background=1&source=${source}${refresh ? '&refresh=1' : ''}`)
      if (id === generation.current) {setData(result); setNow(Date.now())}
    } catch (e) {
      if (id === generation.current) {
        setData(null)
        setError(e instanceof Error ? e.message : 'Could not check clans.')
      }
    } finally {
      if (id === generation.current) setBusy(false)
    }
  }
  useEffect(() => {
    setData(null)
    setExpanded({})
    void load(true)
    return () => {generation.current++}
  }, [seasonId, source])
  useEffect(() => {
    if (!data?.updating || busy || error || editDirty || editBusy || editOpen) return
    const timer = window.setTimeout(() => void load(), 2000)
    return () => window.clearTimeout(timer)
  }, [data, busy, error, editDirty, editBusy, editOpen, seasonId, source])

  const locked = editDirty || editBusy || editOpen
  const clans = new Map<string, Account[]>()
  for (const saved of data?.accounts || []) {
    if (saved.hosting_pool !== pool) continue
    const account = normalizeArrivalAccount(saved, now)
    const key = account.assigned_clan_tag || ''
    clans.set(key, [...(clans.get(key) || []), account])
  }
  const outdated = data?.source === 'published' && data.publication_outdated
  const isReady = (tag: string, accounts: Account[]) => !!tag && summarizeArrivalReadiness(accounts, {now, loading: busy, error: !!error, outdated}).ready
  const readyCount = [...clans].filter(([tag, accounts]) => isReady(tag, accounts)).length
  const allAccounts = [...clans.values()].flat()
  const attention = allAccounts.filter(a => a.arrival_status !== 'arrived').length
  const needle = search.trim().toLocaleLowerCase()
  const groups = [...clans].sort(([a], [b]) => a ? b ? 0 : -1 : 1).map(([tag, accounts]) => ({tag, accounts, visible: accounts.filter(a =>
    (!onlyMissing || a.arrival_status !== 'arrived') && (!needle ||
      [a.player_name, a.tag, a.assigned_clan_name, a.assigned_clan_tag, a.current_clan_name, a.current_clan_tag]
        .some(value => value?.toLocaleLowerCase().includes(needle))))})).filter(group => group.visible.length)

  return <section className="arrival-check" aria-label="Clan arrival checks">
    <div className="arrival-toolbar">
      <CwlPoolTabs value={pool} disabled={locked} onChange={value => {if (!locked) setPool(value)}}/>
      <button disabled={busy || locked} onClick={() => void load(true)}>{busy ? 'Checking…' : 'Refresh locations'}</button>
    </div>
    <div className="arrival-controls">
      <label>Roster source<select value={source} disabled={busy || locked} onChange={e => setSource(e.target.value)}>
        <option value="draft">Working roster</option><option value="published">Published snapshot</option>
      </select></label>
      <label className="arrival-search">Find a player or clan<input type="search" placeholder="Player name, tag or clan" value={search} disabled={locked} onChange={e => setSearch(e.target.value)}/></label>
      <label className="arrival-filter"><input type="checkbox" checked={onlyMissing} disabled={locked} onChange={e => setOnlyMissing(e.target.checked)}/> Needs attention only</label>
    </div>
    {error && <div className="notice error" role="alert"><span>{error}</span><button disabled={busy || locked} onClick={() => void load(true)}>Retry</button></div>}
    {busy && !data && <p role="status">Checking clan locations…</p>}
    {data && <>
      <div className="arrival-overview" role="status">
        <strong>{readyCount} / {[...clans.keys()].filter(Boolean).length} clans ready</strong>
        <span>{attention} accounts need attention</span>
        <small>{data.updating ? 'Updating locations…' : data.source === 'published'
          ? `Published version ${data.version}${data.published_at ? ` · ${new Date(data.published_at).toLocaleString()}` : ''}`
          : 'Working roster'}</small>
      </div>
      {outdated && <div className="notice error" role="status">
        <div><strong>Published roster is outdated</strong>
          <p>Use the working roster to check current declaration readiness.</p>
          <small>{data.removed_since_publication} no longer signed up · {data.added_since_publication} new signups</small>
        </div><button disabled={busy || locked} onClick={() => setSource('draft')}>Use working roster</button>
      </div>}
      {source === 'published' && !data.publication_available && <p role="status">No published roster yet. Showing the working roster.</p>}
      {groups.map(({tag, accounts, visible}) => {
        const arrived = accounts.filter(a => a.arrival_status === 'arrived').length
        const unknown = accounts.filter(a => a.arrival_status === 'unknown').length
        const ready = isReady(tag, accounts)
        const open = expanded[tag] ?? (!!needle || !ready)
        return <section className={`arrival-clan ${ready ? 'arrival-ready' : ''}`} key={tag}>
          <h2 className="arrival-clan-heading"><button aria-expanded={open} disabled={locked} onClick={() => setExpanded(previous => ({...previous, [tag]: !open}))}>
            <span className="arrival-clan-name"><span aria-hidden="true">{open ? '▾' : '▸'}</span> {accounts[0].assigned_clan_name || tag || 'Unassigned accounts'}</span>
            <span className="arrival-clan-count">{tag ? `${arrived}/${accounts.length} arrived` : `${accounts.length} accounts`}</span>
            <span className={`arrival-clan-state ${ready ? 'is-ready' : ''}`}>{ready ? '✓ Ready' : !tag ? 'Needs placement' : unknown ? `${unknown} not checked` : 'Needs attention'}</span>
          </button></h2>
          {open && <div className="arrival-clan-content">
            {tag && accounts.length < 15 && <p className="arrival-minimum">{accounts.length}/15 minimum accounts assigned.</p>}
            {visible.map(a => <div key={a.tag} className={`arrival-account arrival-${a.arrival_status}`}>
              <div className="arrival-identity"><TownHallIcon level={a.town_hall}/><div><strong>{a.player_name}</strong><small>{a.tag} · TH {a.town_hall ?? '—'}</small></div></div>
              <div className="arrival-location"><strong>{a.location_updating ? 'Updating…' : a.arrival_status === 'arrived' ? '✓ Arrived' : a.arrival_status === 'missing' ? 'Not arrived' : a.arrival_status === 'unknown' ? 'Not checked' : 'Needs assignment'}</strong>
                <small>Current: {a.arrival_status === 'unknown' ? 'Unverified' : a.current_clan_name || a.current_clan_tag || 'No clan'}</small>
                {a.outside_family && a.arrival_status !== 'arrived' && <small>Outside family clans</small>}
                {a.current_clan_checked_at && Number.isFinite(Date.parse(a.current_clan_checked_at)) && <small>Checked {new Date(a.current_clan_checked_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</small>}
              </div>
              <div className="arrival-actions"><DiscordContact userId={a.user_id} compact/>
                {source === 'draft' && data.source === 'draft' && <StaffPlayerButton seasonId={seasonId} tag={a.tag} onChanged={() => load(true)} disabled={locked} onDirty={reportDirty} onBusy={setEditBusy} onOpenChange={setEditOpen}>Details</StaffPlayerButton>}
              </div>
            </div>)}
          </div>}
        </section>
      })}
      {!clans.size && <p>No {pool === 'main' ? 'Main' : 'Lazy'} CWL accounts in this roster.</p>}
      {!!clans.size && !groups.length && <p>No accounts match these filters.</p>}
    </>}
    <details className="arrival-help"><summary>What does ready mean?</summary><p>At least 15 assigned accounts, all checked in their hosting clan within the last two minutes. Green means arrived; red means not arrived; gray means not checked. An outdated published roster cannot be ready.</p><p>This checks location only. Staff still start CWL in Clash of Clans.</p></details>
  </section>
}
