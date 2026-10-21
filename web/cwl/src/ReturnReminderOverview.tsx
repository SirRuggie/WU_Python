import ReturnBatch from './returns/ReturnBatch'
import { actionLabels, canApply, clanSection, displayDate, type ReturnAction, type ReturnClan } from './returns/model'
import './returns/returns.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { ManagementDocument, ManagementSection, ReturnStatus } from './serverManagement'

export function ReturnStatusSummary({ status }: { status: ReturnStatus }) {
  return <div className="return-status-grid"><article>
    <strong>{status.label}</strong><span>{status.players} saved players</span>
    {status.every_minutes && <span>Every {status.every_minutes} minutes</span>}
    <small>Last recorded send: {status.last_sent_at ? new Date(status.last_sent_at).toLocaleString() : 'None recorded'}</small>
    {status.expires_at && <small>Window ends: {new Date(status.expires_at).toLocaleString()}</small>}
  </article></div>
}

export default function ReturnReminderOverview({ onOpen, onDirty, active = true }: { active?: boolean; onOpen: (section: ManagementSection) => void; onDirty?: (dirty: boolean) => void }) {
  const [records, setRecords] = useState<ReturnClan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [section, setSection] = useState<'FWA'|'MAIN'>('FWA')
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState<string[]>([])
  const [action, setAction] = useState<ReturnAction>('start')
  const [batch, setBatch] = useState<{action: ReturnAction; clans: ReturnClan[]}|null>(null)
  const [loadedAt, setLoadedAt] = useState('')
  const focusTarget = useRef<HTMLElement|null>(null)
  const request = useRef(0)
  useEffect(() => { if(active) focusTarget.current?.focus() }, [active])
  const load = useCallback(async () => {
    const id = ++request.current
    setLoading(true); setError('')
    try {
      const result = await api<ManagementDocument>('/manage/return-reminders')
      if (id !== request.current) return
      setRecords(result.documents || []); setLoadedAt(new Date().toLocaleTimeString())
      setSelected(current => current.filter(id => result.documents?.some(row => row.id === id)))
    } catch (cause) {
      if (id !== request.current) return
      if (cause instanceof ApiError && [401,403].includes(cause.status)) { setRecords([]); setSelected([]); setLoadedAt('') }
      setError(cause instanceof Error ? cause.message : 'Could not load return reminders.')
    } finally { if (id === request.current) setLoading(false) }
  }, [])
  useEffect(() => { if(active) void load(); return () => { request.current++ } }, [load, active])
  useEffect(() => { onDirty?.(!!batch); return () => onDirty?.(false) }, [!!batch, onDirty])
  const clans = records.filter(row => row.return_status)
  const group = clans.filter(row => clanSection(row) === section)
  const visible = group.filter(row => (filter === 'all' || row.return_status?.state === filter) && `${row.label} ${row.id}`.toLowerCase().includes(query.trim().toLowerCase()))
  const chosen = group.filter(row => selected.includes(row.id))
  const incompatible = chosen.filter(row => !canApply(row,action)).length
  const utility = (id: string) => { const row = records.find(row => row.id === id); if(row) onOpen(row) }
  const actions: ReturnAction[] = section === 'FWA' ? ['start','pause','resume','save','send','away'] : ['send','save','away']
  return <section className="return-overview" aria-label="Return reminder overview" onClickCapture={event => { const target = (event.target as HTMLElement).closest('button'); if(target && !batch) focusTarget.current = target }} >
    <div className="return-toolbar"><div className="workflow-tabs" role="group" aria-label="Home clan type">
      {(['FWA','MAIN'] as const).map(value => <button key={value} aria-pressed={section === value} disabled={!!batch} onClick={() => {setSection(value);setFilter('all');setSelected([]);setAction(value === 'FWA' ? 'start' : 'send')}}>{value === 'MAIN' ? 'Main' : value}<span>{clans.filter(row => clanSection(row) === value).length}</span></button>)}
    </div><div><button disabled={loading || !!batch} onClick={() => void load()}>Refresh</button><button disabled={loading || !!batch} onClick={() => utility('return-channels')}>Return channels</button></div></div>
    <p>{section === 'FWA' ? 'Capture members before they leave. After declaration, select your clans and start automated reminders. No start date is needed.' : 'Capture members before they leave. When they should return, select your Main clans and send a reminder. Main reminders are always manual.'}</p>
    {error && <div className="notice error" role="alert">{error}{loadedAt && ' Showing the last loaded overview.'}<button disabled={loading} onClick={() => void load()}>Retry</button></div>}
    {loading && <p role="status">Loading return lists…</p>}
    {batch && <ReturnBatch key={batch.action+batch.clans.map(row=>row.id).join(',')} {...batch} onClose={() => {setBatch(null); requestAnimationFrame(() => focusTarget.current?.focus())}} onDone={() => {if(batch.action === 'save') setAction(section === 'FWA' ? 'start' : 'send');void load()}}/>}
    <fieldset disabled={!!batch || loading || !!error}>
      <div className="return-filters"><label>Find a clan<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Clan name or tag"/></label><label>Status<select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All statuses</option>{(section === 'FWA' ? [['scheduled','Running / scheduled'],['paused','Paused'],['idle','Not started'],['not_saved','No saved list'],['expired','Window ended']] : [['manual','Ready for manual sends'],['not_saved','No saved list'],['expired','Window ended']]).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
      <div className="return-bulk-bar"><label>Action<select value={action} onChange={event => setAction(event.target.value as ReturnAction)}>{actions.map(value => <option key={value} value={value}>{actionLabels[value]}</option>)}</select></label><div className="return-selection-controls"><label className="return-select-all"><input type="checkbox"
        ref={node => {if(node) node.indeterminate = visible.some(row => selected.includes(row.id)) && !visible.every(row => selected.includes(row.id))}}
        checked={visible.length > 0 && visible.every(row => selected.includes(row.id))}
        disabled={!visible.length} onChange={event => setSelected(current => event.target.checked
          ? [...new Set([...current,...visible.map(row=>row.id)])]
          : current.filter(id => !visible.some(row => row.id === id)))}/>
        {query.trim() || filter !== 'all' ? 'Select all matching clans' : `Select all ${section === 'MAIN' ? 'Main' : 'FWA'} clans`} ({visible.length})</label>
        <button disabled={!selected.length} onClick={() => setSelected([])}>Clear selection</button></div><span>{chosen.length} selected{chosen.filter(row=>!visible.includes(row)).length > 0 && ' · Includes hidden selections'}</span><button className="primary" disabled={!chosen.length || chosen.length > 50 || incompatible > 0} onClick={() => setBatch({action,clans:chosen})}>{actionLabels[action]}{chosen.length ? ` (${chosen.length})` : ''}</button></div>
      {incompatible > 0 && <p role="status">{incompatible} selected clans cannot {actionLabels[action].toLowerCase()}.{action === 'save' ? ' They already have a saved list. Keep it for members who are away; select only clans without a list to capture members.' : ' Check their list status below or choose another action.'}{action === 'send' && chosen.some(row => row.return_status?.state === 'not_saved') && ' Capture current members first for clans without a list.'}</p>}
      {chosen.length > 50 && <p role="alert">Choose up to 50 clans per action.</p>}
      {section === 'FWA' && <details className="return-maintenance">
        <summary>Optional scheduling settings</summary>
        <p>Need a different window? Select one or more clans, then set their start and stop dates.</p>
        <button disabled={!chosen.length || chosen.length > 50 || chosen.some(row => !canApply(row,'schedule'))}
          onClick={() => setBatch({action:'schedule',clans:chosen})}>Schedule for later{chosen.length ? ` (${chosen.length})` : ''}</button>
      </details>}
      <div className="return-clan-list">{visible.map(row => <article key={row.id} className="return-clan-row">
        <label className="return-clan-name"><input type="checkbox" checked={selected.includes(row.id)} aria-label={`Select ${row.clan_name || row.label}`} onChange={event => setSelected(current => event.target.checked ? [...current,row.id] : current.filter(id=>id!==row.id))}/><span><strong>{row.clan_name || row.label}</strong><small>{row.clan_tag || row.id.replace(/^(MAIN|FWA)/,'')} · {row.return_status!.players} saved players</small></span></label>
        <div><strong>{row.return_status!.label}</strong><small>{section === 'FWA' ? row.return_status!.every_minutes ? `Every ${row.return_status!.every_minutes} minutes` : 'No schedule' : 'Manual sends only'}</small></div>
        <div className="return-window">{section === 'FWA' && row.return_status!.starts_at && <small>Started / scheduled: {displayDate(row.return_status!.starts_at)}</small>}{row.return_status!.expires_at && <small>{section === 'FWA' ? 'Automatically stops' : 'List expires'}: {displayDate(row.return_status!.expires_at)}</small>}<small>Last sent: {row.return_status!.last_sent_at ? displayDate(row.return_status!.last_sent_at) : 'None recorded'}</small></div>
        <div className="return-row-actions"><button onClick={() => onOpen(row)}>Members &amp; details</button></div>
      </article>)}</div>
    </fieldset>
    {!loading && !error && !visible.length && <p>{group.length ? 'No clans match these filters.' : 'No home clans are available yet.'}</p>}
    <p className="small">{loadedAt && `Updated ${loadedAt}. `}Times use {Intl.DateTimeFormat().resolvedOptions().timeZone}. Running describes saved settings; last-send timestamps are delivery records, not a live worker-health check.</p>
    <details className="return-maintenance"><summary>Recent actions &amp; list maintenance</summary><div><button disabled={!!batch} onClick={() => utility('return-history')}>Recent actions and results</button>{['replace','clear'].map(operation => <button key={operation} disabled={!!batch} onClick={() => utility('return-bulk-'+operation)}>{operation === 'replace' ? 'Replace saved member lists' : 'Close saved lists'}</button>)}</div></details>
  </section>
}
