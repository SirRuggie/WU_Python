import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import MemberPicker from './MemberPicker'
import './AccessSettings.css'

type Grant = { kind: 'user' | 'role'; id: string; label: string; permissions: string[] }
type Permission = { id: string; label: string; description: string }
type AccessData = {
  revision: number; grants: Grant[]; owners: string[];
  groups: { label: string; permissions: Permission[] }[];
  history: { at: string; actor_id: string; kind: string; subject_id: string; before: Grant | null; after: Grant | null }[]
}
export default function AccessSettings({ onDirty }: { onDirty?: (dirty: boolean) => void }) {
  const [data, setData] = useState<AccessData | null>(null)
  const [kind, setKind] = useState<'user' | 'role'>('user')
  const [id, setId] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [group, setGroup] = useState(0)
  const [roles, setRoles] = useState<{ id: string; name: string }[]>([])
  const [roleSearch, setRoleSearch] = useState('')
  const [roleError, setRoleError] = useState('')
  const [roleReload, setRoleReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [remove, setRemove] = useState<Grant | null>(null)
  const [editing, setEditing] = useState(false)
  const sequence = useRef(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const current = data?.grants.find(g => g.kind === kind && g.id === id)
  const dirty = JSON.stringify([...selected].sort()) !== JSON.stringify([...(current?.permissions || [])].sort())

  useEffect(() => { onDirty?.(dirty); return () => onDirty?.(false) }, [dirty, onDirty])

  async function load() {
    const turn = ++sequence.current
    setLoading(true); setError('')
    try {
      const result = await api<AccessData>('/access')
      if (turn === sequence.current) setData(result)
    } catch (e) {
      if (turn !== sequence.current) return
      if (e instanceof ApiError && [401, 403].includes(e.status)) setData(null)
      setError(e instanceof Error ? e.message : 'Could not load access.')
    } finally { if (turn === sequence.current) setLoading(false) }
  }
  useEffect(() => { void load(); return () => { sequence.current++ } }, [])
  useEffect(() => {
    if (!editing || kind !== 'role') return
    let active = true
    setRoleError('')
    api<{ roles: { id: string; name: string }[] }>('/access/roles').then(result => {
      if (active) setRoles(result.roles)
    }).catch(e => { if (active) setRoleError(e.message) })
    return () => { active = false }
  }, [editing, kind, roleReload])
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [dirty])
  function leave() { return !dirty || window.confirm('Discard unsaved access changes?') }
  function edit(grant?: Grant) {
    if (!leave()) return
    setKind(grant?.kind || 'user'); setId(grant?.id || '')
    setSelected(grant?.permissions || []); setGroup(0); setEditing(true)
    setRemove(null); setError(''); setNotice('')
    requestAnimationFrame(() => heading.current?.focus())
  }
  async function save(target: Grant | null = null) {
    if (!data) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api<AccessData>('/access', 'POST', {
        revision: data.revision, kind: target?.kind || kind, id: target?.id || id,
        permissions: target ? null : selected,
      })
      setData(result); setEditing(false); setId(''); setSelected([]); setRemove(null)
      setNotice(target ? 'Access entry removed. Other user or role grants still apply.' : 'Access saved. Only the selected actions are granted.')
    } catch (e) {
      if (e instanceof ApiError && [401, 403].includes(e.status)) { setData(null); setEditing(false) }
      setError(e instanceof Error ? e.message : 'Save could not be confirmed. Reload access before trying again.')
    } finally { setBusy(false) }
  }
  const labels = Object.fromEntries(data?.groups.flatMap(g => g.permissions.map(p => [p.id, p.label])) || [])
  return <div className="access-workspace">
    <div className="page-head"><div><p className="eyebrow">Owner controls</p><h1>Dashboard access</h1><p>Choose who can manage each area. All clans are included. CWL permissions cover Main and Lazy.</p></div></div>
    <div className="access-toolbar"><span>{data ? `${data.grants.length} access entries · 2 protected owners` : 'Staff permissions'}</span><div><button disabled={busy || loading} onClick={() => { if (leave()) { setEditing(false); setSelected([]); setId(''); void load() } }}>Refresh access</button><button className="primary" disabled={busy || !data} onClick={() => edit()}>Add access</button></div></div>
    {error && <div className="notice error" role="alert">{error} Use Refresh access to check saved permissions.</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {loading && <p role="status">Loading access…</p>}
    {editing && data && <section className="card">
      <h2 ref={heading} tabIndex={-1}>{current ? 'Edit access' : 'Add access'}</h2>
      <form onSubmit={event => { event.preventDefault(); void save() }}>
        <fieldset disabled={busy}><legend>Who gets access?</legend><div className="access-subject">
          <label><input type="radio" checked={kind === 'user'} onChange={() => { if (leave()) { setKind('user'); setId(''); setSelected([]) } }} />Specific member</label>
          <label><input type="radio" checked={kind === 'role'} onChange={() => { if (leave()) { setKind('role'); setId(''); setSelected([]) } }} />Discord role</label>
        </div></fieldset>
        {kind === 'user' ? <MemberPicker label="Staff member" value={id} disabled={busy} onChange={value => { if (!leave()) return; const next = String(value || ''); setId(next); setSelected(data.grants.find(g => g.kind === kind && g.id === next)?.permissions || []) }} /> : <div className="access-role-picker">
          <label>Find a role<input type="search" value={roleSearch} disabled={busy} onChange={e => setRoleSearch(e.target.value)} placeholder="Type a role name" /></label>
          <label>Discord role<select value={id} disabled={busy} onChange={e => { if (!leave()) return; setId(e.target.value); setSelected(data.grants.find(g => g.kind === 'role' && g.id === e.target.value)?.permissions || []) }}><option value="">Select a role</option>{roles.filter(r => r.id === id || r.name.toLowerCase().includes(roleSearch.toLowerCase())).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
          {roleError && <div role="alert">{roleError}<button type="button" disabled={busy} onClick={() => setRoleReload(v => v + 1)}>Retry role list</button></div>}
          <p className="small">Members receive these permissions while they hold this role. User and role grants add together.</p>
        </div>}
        <h3>Allowed actions</h3>
        <div className="access-groups" role="group" aria-label="Permission areas">{data.groups.map((item, index) => <button type="button" key={item.label} aria-pressed={group === index} className={group === index ? 'active' : ''} disabled={busy} onClick={() => setGroup(index)}>{item.label} <span>{item.permissions.filter(p => selected.includes(p.id)).length}</span></button>)}</div>
        <fieldset className="access-options" disabled={busy}><legend>{data.groups[group].label}</legend>{data.groups[group].permissions.map(p => <label key={p.id}><input type="checkbox" checked={selected.includes(p.id)} onChange={e => setSelected(old => e.target.checked ? [...old, p.id] : old.filter(v => v !== p.id))} /><span><strong>{p.label}</strong><small>{p.description}</small></span></label>)}</fieldset>
        <div className="access-toolbar"><span>{selected.length} actions selected · Access management is owner-only</span><div><button type="button" disabled={busy} onClick={() => { if (leave()) { setEditing(false); setId(''); setSelected([]) } }}>Cancel</button><button className="primary" disabled={busy || !id || !selected.length || !dirty || (kind === 'user' && data.owners.includes(id))}>{busy ? 'Saving…' : 'Save access'}</button></div></div>
      </form>
    </section>}
    {data && <section className="card"><h2>Staff access</h2>{!data.grants.length && <p>No added staff. Only the two owners have access.</p>}{data.grants.map(grant => <div className="access-row" key={`${grant.kind}:${grant.id}`}><div><strong>{grant.label}</strong><small>{grant.kind === 'role' ? 'Discord role' : 'Member'} · {grant.id}</small><p>{grant.permissions.map(p => labels[p] || p).join(' · ')}</p></div><div className="access-row-actions"><button disabled={busy} onClick={() => edit(grant)}>Edit</button><button disabled={busy || editing} onClick={() => setRemove(grant)}>Remove</button></div></div>)}</section>}
    {remove && <div className="notice error" role="alert"><p>Remove this access entry for <strong>{remove.label}</strong>? Other grants still apply.</p><div className="access-row-actions"><button disabled={busy} onClick={() => setRemove(null)}>Cancel</button><button disabled={busy} onClick={() => void save(remove)}>Remove access entry</button></div></div>}
    {data && <details className="card"><summary>Access history · latest 200 changes</summary>{data.history.length ? [...data.history].reverse().map((row, i) => <p key={i}><strong>{row.after ? 'Saved' : 'Removed'} {row.after?.label || row.before?.label || row.subject_id}</strong><br /><small>{new Date(row.at).toLocaleString()} · Owner {row.actor_id}</small><br />{row.after?.permissions.map(p => labels[p] || p).join(' · ') || 'Entry removed'}</p>) : <p>No changes recorded in the new access settings yet.</p>}</details>}
  </div>
}
