import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { strikePermissions } from './strikePermissions'
import { groupReplacements } from './replacementView'
import './ReplacementWorkspace.css'

type Priority = 'replace_first' | 'high' | 'normal'
type Clan = { tag: string; name: string; is_fwa?: boolean }
type Candidate = { player_tag: string; player_name: string; clan_tag?: string | null; clan_name?: string | null; priority?: Priority; note?: string | null; weight?: number | null; weight_difference?: number | null; active_strikes: number; clan_is_current?: boolean; clan_seen_at?: string | null; is_manual?: boolean; is_filler?: boolean }
type Result = { candidates: Candidate[]; clans?: Clan[] }
const priorityLabels: Record<Priority, string> = { replace_first: 'Replace first', high: 'High', normal: 'Normal' }
const priorityOf = (item: Candidate): Priority => item.priority || (item.is_filler ? 'replace_first' : 'normal')
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Could not load replacements. Try again.'
const tagPath = (tag: string) => encodeURIComponent(tag)

export default function ReplacementWorkspace({ permissions, isOwner }: { permissions: string[]; isOwner: boolean }) {
  const canManage = strikePermissions(permissions, isOwner).manage
  const [items, setItems] = useState<Candidate[]>([])
  const [clans, setClans] = useState<Clan[]>([])
  const [clan, setClan] = useState('')
  const [search, setSearch] = useState('')
  const [weightDraft, setWeightDraft] = useState('')
  const [weight, setWeight] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [adding, setAdding] = useState(false)
  const [newTag, setNewTag] = useState('')
  const [newPriority, setNewPriority] = useState<Priority>('normal')
  const [newNote, setNewNote] = useState('')
  const [editing, setEditing] = useState('')
  const [editPriority, setEditPriority] = useState<Priority>('normal')
  const [editNote, setEditNote] = useState('')
  const request = useRef(0)

  const load = useCallback(async () => {
    const current = ++request.current
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams()
      if (weight) params.set('weight', weight)
      if (clan) params.set('clan', clan)
      const result = await api<Result>(`/strikes/replacements${params.toString() ? `?${params}` : ''}`)
      if (current !== request.current) return
      setItems(result.candidates || [])
      setClans(existing => [...new Map([...existing, ...(result.clans || [])].map(item => [item.tag, item])).values()])
    } catch (err) { if (current === request.current) setError(errorText(err)) }
    finally { if (current === request.current) setLoading(false) }
  }, [weight, clan])
  useEffect(() => { void load() }, [load])

  const save = async (action: () => Promise<unknown>, message: string, after: () => void) => {
    setBusy(true); setError(''); setNotice('')
    try { await action(); after(); await load(); setNotice(message) }
    catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  const visible = items.filter(item => !search.trim() || `${item.player_name} ${item.player_tag} ${item.clan_name || ''}`.toLowerCase().includes(search.trim().toLowerCase()))
  const groups = groupReplacements(visible)

  return <section className="replacement-workspace">
    <div className="page-head"><div><p className="eyebrow">Strikes</p><h1>Replacements</h1><p>Review accounts by clan and priority.</p></div>{canManage && <button className="primary" onClick={() => { setAdding(value => !value); setEditing('') }}>{adding ? 'Close' : 'Add account'}</button>}</div>
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Retry</button></div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {adding && canManage && <form className="card replacement-editor" onSubmit={event => { event.preventDefault(); if (!newTag.trim()) return; void save(() => api('/strikes/replacement-list', 'POST', { player_tag: newTag.trim(), priority: newPriority, note: newNote.trim() }), 'Account added.', () => { setAdding(false); setNewTag(''); setNewNote(''); setNewPriority('normal') }) }}><h2>Add account</h2><label>Player tag<input value={newTag} onChange={event => setNewTag(event.target.value)} placeholder="#PLAYERTAG" required /></label><label>Priority<select value={newPriority} onChange={event => setNewPriority(event.target.value as Priority)}><option value="replace_first">Replace first</option><option value="high">High</option><option value="normal">Normal</option></select></label><label>Note (optional)<input value={newNote} onChange={event => setNewNote(event.target.value)} maxLength={300} placeholder="e.g. Temporary filler" /></label><button className="primary" disabled={busy || !newTag.trim()}>{busy ? 'Saving…' : 'Add to list'}</button></form>}
    <div className="replacement-filters"><label>Find account<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name or player tag" /></label><label>Clan<select value={clan} onChange={event => setClan(event.target.value)}><option value="">All clans</option>{clans.filter(item => !weight || item.is_fwa).map(item => <option key={item.tag} value={item.tag}>{item.name}</option>)}</select></label><form onSubmit={event => { event.preventDefault(); const nextWeight = weightDraft.trim(); if (nextWeight && clan && !clans.find(item => item.tag === clan)?.is_fwa) setClan(''); setWeight(nextWeight) }}><label>Recruit war weight (optional)<input type="number" min="1" step="1" value={weightDraft} onChange={event => setWeightDraft(event.target.value)} placeholder="e.g. 115000" /></label><button type="submit">Match</button>{weight && <button type="button" onClick={() => { setWeight(''); setWeightDraft('') }}>Clear</button>}</form></div>
    {weight && <p className="replacement-weight-note">FWA only · priority, strikes, then weight ({Number(weight).toLocaleString()}).</p>}
    <div className="replacement-count" role="status">{loading ? 'Loading replacements…' : `${error ? 0 : visible.length} ${visible.length === 1 ? 'account' : 'accounts'}`}</div>
    {!loading && !error && visible.length === 0 && <div className="card replacement-empty">{search ? 'No accounts match.' : 'No replacement accounts yet.'}</div>}
    {!loading && !error && groups.map(group => <section className="replacement-group" key={group.tag}><div className="replacement-group-head"><h2>{group.name}</h2><span>{group.accounts.length}</span></div><div className="replacement-list">{group.accounts.map(item => <article className="card replacement-row" key={item.player_tag}><div className="replacement-row-main"><div className="replacement-identity"><strong>{item.player_name || item.player_tag}</strong><small>{item.player_tag}{item.clan_is_current === false ? ' · Last known clan' : ''}</small></div><span className={`replacement-priority ${priorityOf(item)}`}>{priorityLabels[priorityOf(item)]}</span><div className="replacement-stats"><span>{item.active_strikes} active {item.active_strikes === 1 ? 'strike' : 'strikes'}</span><span>Weight {item.weight == null ? '—' : item.weight.toLocaleString()}</span>{weight && <span>Gap {item.weight_difference == null ? '—' : item.weight_difference.toLocaleString()}</span>}</div>{canManage && <button className="replacement-more" aria-label={`Edit ${item.player_name || item.player_tag}`} aria-expanded={editing === item.player_tag} onClick={() => { if (editing === item.player_tag) { setEditing(''); return } setEditing(item.player_tag); setAdding(false); setEditPriority(priorityOf(item)); setEditNote(item.note || '') }}>⋯</button>}</div>{item.note && <p className="replacement-note">{item.note}</p>}{editing === item.player_tag && canManage && <form className="replacement-edit-panel" onSubmit={event => { event.preventDefault(); void save(() => api(`/strikes/replacement-list/${tagPath(item.player_tag)}`, 'PUT', { priority: editPriority, note: editNote.trim() }), 'Priority saved.', () => setEditing('')) }}><label>Priority<select value={editPriority} onChange={event => setEditPriority(event.target.value as Priority)}><option value="replace_first">Replace first</option><option value="high">High</option><option value="normal">Normal</option></select></label><label>Note<input value={editNote} onChange={event => setEditNote(event.target.value)} maxLength={300} placeholder="Optional" /></label><div className="replacement-edit-actions"><button className="primary" disabled={busy}>Save</button>{item.is_manual && <button type="button" disabled={busy} onClick={() => { if (!window.confirm(`Clear ${item.player_name || item.player_tag}'s replacement priority? Strike history stays.`)) return; void save(() => api(`/strikes/replacement-list/${tagPath(item.player_tag)}`, 'DELETE'), 'Priority cleared.', () => setEditing('')) }}>Clear priority</button>}</div>{item.is_manual && <small>Strike history stays.</small>}</form>}</article>)}</div></section>)}
  </section>
}
