import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { strikePermissions } from './strikePermissions'
import { bulkSaveMessage, compactWeight, enteredWeight, groupReplacements, selectableTags, toggleRosterTag, type RosterAccount } from './replacementView'
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
  const [addMode, setAddMode] = useState<'roster' | 'tag'>('roster')
  const [newClan, setNewClan] = useState('')
  const [roster, setRoster] = useState<RosterAccount[]>([])
  const [rosterLoading, setRosterLoading] = useState(false)
  const [rosterError, setRosterError] = useState('')
  const [rosterRetry, setRosterRetry] = useState(0)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [newTag, setNewTag] = useState('')
  const [newPriority, setNewPriority] = useState<Priority>('normal')
  const [newNote, setNewNote] = useState('')
  const [editing, setEditing] = useState('')
  const [editPriority, setEditPriority] = useState<Priority>('normal')
  const [editNote, setEditNote] = useState('')
  const request = useRef(0)
  const rosterRequest = useRef(0)
  useEffect(() => {
    const current = ++rosterRequest.current
    if (!adding || addMode !== 'roster' || !newClan) { setRoster([]); setSelectedTags([]); setRosterError(''); setRosterLoading(false); return }
    setRoster([]); setSelectedTags([]); setRosterError(''); setRosterLoading(true)
    void api<{ accounts: RosterAccount[] }>(`/strikes/replacement-roster?clan=${encodeURIComponent(newClan)}`)
      .then(result => { if (current === rosterRequest.current) setRoster(result.accounts || []) })
      .catch(err => { if (current === rosterRequest.current) setRosterError(errorText(err)) })
      .finally(() => { if (current === rosterRequest.current) setRosterLoading(false) })
    return () => { rosterRequest.current++ }
  }, [adding, addMode, newClan, rosterRetry])

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

  const save = async <T,>(action: () => Promise<T>, message: string | ((result: T) => string), after: () => void) => {
    setBusy(true); setError(''); setNotice('')
    try { const result = await action(); after(); await load(); setNotice(typeof message === 'function' ? message(result) : message) }
    catch (err) {
      await load()
      if (adding && addMode === 'roster') setRosterRetry(value => value + 1)
      setError(`${errorText(err)} The list has been refreshed; check it before retrying.`)
    }
    finally { setBusy(false) }
  }
  const visible = items.filter(item => !search.trim() || `${item.player_name} ${item.player_tag} ${item.clan_name || ''}`.toLowerCase().includes(search.trim().toLowerCase()))
  const groups = groupReplacements(visible)

  return <section className="replacement-workspace">
    <div className="page-head"><div><p className="eyebrow">Strikes</p><h1>Replacements</h1><p>Review accounts by clan and priority.</p></div>{canManage && <button className="primary" disabled={busy} onClick={() => { if (!adding) { setNewClan(clan); setAddMode('roster'); setSelectedTags([]) } else { setSelectedTags([]) } setAdding(value => !value); setEditing('') }}>{adding ? 'Close' : 'Add accounts'}</button>}</div>
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Retry</button></div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {adding && canManage && <form className="card replacement-editor" onSubmit={event => {
      event.preventDefault()
      if (addMode === 'roster') {
        if (!newClan || !selectedTags.length || rosterLoading || rosterError) return
        const tags = [...selectedTags]
        void save(() => api<{ added_count: number; skipped_count: number }>('/strikes/replacement-list/bulk', 'POST', { clan_tag: newClan, player_tags: tags, priority: newPriority, note: newNote.trim() }), bulkSaveMessage, () => { setAdding(false); setSelectedTags([]); setNewNote(''); setNewPriority('normal') })
      } else {
        if (!newTag.trim()) return
        void save(() => api('/strikes/replacement-list', 'POST', { player_tag: newTag.trim(), priority: newPriority, note: newNote.trim() }), 'Account added.', () => { setAdding(false); setNewTag(''); setNewNote(''); setNewPriority('normal') })
      }
    }}><h2>Add accounts</h2><label className="replacement-add-mode">Choose from<select value={addMode} disabled={busy} onChange={event => { setAddMode(event.target.value as 'roster' | 'tag'); setSelectedTags([]) }}><option value="roster">Clan roster</option><option value="tag">Player tag</option></select></label>
      {addMode === 'roster' ? <><label className="replacement-clan-choice">Clan<select value={newClan} disabled={busy} onChange={event => { setNewClan(event.target.value); setSelectedTags([]) }} required><option value="">Choose clan</option>{clans.map(item => <option key={item.tag} value={item.tag}>{item.name}</option>)}</select></label>
        {newClan && <div className="replacement-roster"><div className="replacement-roster-head"><strong>Accounts</strong>{!rosterLoading && !rosterError && selectableTags(roster).length > 0 && <button type="button" disabled={busy} onClick={() => setSelectedTags(selectedTags.length === selectableTags(roster).length ? [] : selectableTags(roster))}>{selectedTags.length === selectableTags(roster).length ? 'Clear all' : 'Select all'}</button>}</div>
          {rosterLoading ? <p role="status">Loading roster…</p> : rosterError ? <div className="notice error" role="alert">{rosterError}<button type="button" onClick={() => setRosterRetry(value => value + 1)}>Retry</button></div> : roster.length ? <div className="replacement-roster-list">{roster.map(account => <label key={account.player_tag} className={account.is_manual ? 'is-listed' : ''}><input type="checkbox" checked={account.is_manual || selectedTags.includes(account.player_tag)} disabled={busy || account.is_manual} onChange={() => setSelectedTags(current => toggleRosterTag(current, account.player_tag, roster))} /><span><strong>{account.player_name || account.player_tag}</strong><small>{account.player_tag}</small></span>{account.is_manual && <small>Listed</small>}</label>)}</div> : <p>No accounts found in this clan.</p>}</div>}
      </> : <label className="replacement-tag-choice">Player tag<input value={newTag} disabled={busy} onChange={event => setNewTag(event.target.value)} placeholder="#PLAYERTAG" required /></label>}
      <div className="replacement-add-details"><label>Priority<select value={newPriority} disabled={busy} onChange={event => setNewPriority(event.target.value as Priority)}><option value="replace_first">Replace first</option><option value="high">High</option><option value="normal">Normal</option></select></label><label>Note (optional)<input value={newNote} disabled={busy} onChange={event => setNewNote(event.target.value)} maxLength={300} placeholder="e.g. Temporary filler" /></label></div>
      <button className="primary" disabled={busy || (addMode === 'roster' ? !newClan || !selectedTags.length || rosterLoading || !!rosterError : !newTag.trim())}>{busy ? 'Saving…' : addMode === 'roster' ? `Add ${selectedTags.length} ${selectedTags.length === 1 ? 'account' : 'accounts'}` : 'Add account'}</button></form>}
    <div className="replacement-filters"><label>Find account<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name or player tag" /></label><label>Clan<select value={clan} onChange={event => setClan(event.target.value)}><option value="">All clans</option>{clans.filter(item => !weight || item.is_fwa).map(item => <option key={item.tag} value={item.tag}>{item.name}</option>)}</select></label><form onSubmit={event => { event.preventDefault(); const nextWeight = weightDraft.trim(); if (nextWeight && clan && !clans.find(item => item.tag === clan)?.is_fwa) setClan(''); setWeight(nextWeight) }}><label>Recruit war weight (optional)<input type="number" min="1" step="1" value={weightDraft} onChange={event => setWeightDraft(event.target.value)} placeholder="e.g. 149" /></label><button type="submit">Match</button>{weight && <button type="button" onClick={() => { setWeight(''); setWeightDraft('') }}>Clear</button>}</form></div>
    {weight && <p className="replacement-weight-note">FWA only · priority, strikes, then weight ({compactWeight(enteredWeight(weight))}).</p>}
    <div className="replacement-count" role="status">{loading ? 'Loading replacements…' : `${error ? 0 : visible.length} ${visible.length === 1 ? 'account' : 'accounts'}`}</div>
    {!loading && !error && visible.length === 0 && <div className="card replacement-empty">{search ? 'No accounts match.' : 'No replacement accounts yet.'}</div>}
    {!loading && !error && groups.map(group => <section className="replacement-group" key={group.tag}><div className="replacement-group-head"><h2>{group.name}</h2><span>{group.accounts.length}</span></div><div className="replacement-list">{group.accounts.map(item => <article className="card replacement-row" key={item.player_tag}><div className="replacement-row-main"><div className="replacement-identity"><strong>{item.player_name || item.player_tag}</strong><small>{item.player_tag}{item.clan_is_current === false ? ' · Last known clan' : ''}</small></div><span className={`replacement-priority ${priorityOf(item)}`}>{priorityLabels[priorityOf(item)]}</span><div className="replacement-stats"><span>{item.active_strikes} active {item.active_strikes === 1 ? 'strike' : 'strikes'}</span><span>Weight {item.weight == null ? '—' : compactWeight(item.weight)}</span>{weight && <span>Gap {item.weight_difference == null ? '—' : compactWeight(item.weight_difference)}</span>}</div>{canManage && <button className="replacement-more" aria-label={`Edit ${item.player_name || item.player_tag}`} aria-expanded={editing === item.player_tag} onClick={() => { if (editing === item.player_tag) { setEditing(''); return } setEditing(item.player_tag); setAdding(false); setEditPriority(priorityOf(item)); setEditNote(item.note || '') }}>⋯</button>}</div>{item.note && <p className="replacement-note">{item.note}</p>}{editing === item.player_tag && canManage && <form className="replacement-edit-panel" onSubmit={event => { event.preventDefault(); void save(() => api(`/strikes/replacement-list/${tagPath(item.player_tag)}`, 'PUT', { priority: editPriority, note: editNote.trim() }), 'Priority saved.', () => setEditing('')) }}><label>Priority<select value={editPriority} onChange={event => setEditPriority(event.target.value as Priority)}><option value="replace_first">Replace first</option><option value="high">High</option><option value="normal">Normal</option></select></label><label>Note<input value={editNote} onChange={event => setEditNote(event.target.value)} maxLength={300} placeholder="Optional" /></label><div className="replacement-edit-actions"><button className="primary" disabled={busy}>Save</button>{item.is_manual && <button type="button" disabled={busy} onClick={() => { if (!window.confirm(`Clear ${item.player_name || item.player_tag}'s replacement priority? Strike history stays.`)) return; void save(() => api(`/strikes/replacement-list/${tagPath(item.player_tag)}`, 'DELETE'), 'Priority cleared.', () => setEditing('')) }}>Clear priority</button>}</div>{item.is_manual && <small>Strike history stays.</small>}</form>}</article>)}</div></section>)}
  </section>
}
