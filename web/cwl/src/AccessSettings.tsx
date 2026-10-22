import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import MemberPicker, { type MemberOption } from './MemberPicker'
import AccessPermissions from './AccessPermissions'
import './AccessSettings.css'
import AccessAvatar from './AccessAvatar'

type Grant = { kind: 'user' | 'role'; id: string; label: string; permissions: string[]; display_name?: string; username?: string; avatar_url?: string | null; identity_status?: 'current' | 'missing' | 'unavailable' }
type Permission = { id: string; label: string; description: string }
type AccessData = {
  revision: number; grants: Grant[]; owners: string[];
  groups: { label: string; permissions: Permission[] }[];
  history: { at: string; actor_id: string; kind: string; subject_id: string; before: Grant | null; after: Grant | null }[]
}
export default function AccessSettings({ onDirty }: { onDirty?: (dirty: boolean) => void }) {
  const [data, setData] = useState<AccessData | null>(null)
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<'user' | 'role'>('user')
  const [id, setId] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [members, setMembers] = useState<MemberOption[]>([])
  const [choosing, setChoosing] = useState(false)
  const [roles, setRoles] = useState<{ id: string; name: string }[]>([])
  const [roleSearch, setRoleSearch] = useState('')
  const [rolesLoading, setRolesLoading] = useState(false)
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
    if (!editing || !choosing || kind !== 'role') return
    let active = true
    setRoleError(''); setRolesLoading(true)
    api<{ roles: { id: string; name: string }[] }>('/access/roles').then(result => {
      if (active) setRoles(result.roles)
    }).catch(e => { if (active) setRoleError(e.message) }).finally(() => { if (active) setRolesLoading(false) })
    return () => { active = false }
  }, [editing, choosing, kind, roleReload])
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [dirty])
  function leave() { return !dirty || window.confirm('Discard unsaved access changes?') }
  function edit(grant?: Grant) {
    if (!leave()) return
    setKind(grant?.kind || 'user'); setId(grant?.id || '')
    setSelected(grant?.permissions || []); setChoosing(!grant); setEditing(true)
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
      requestAnimationFrame(() => document.getElementById('access-list-title')?.focus())
      setNotice(target ? 'Access entry removed. Other user or role grants still apply.' : 'Access saved. Only the selected actions are granted.')
    } catch (e) {
      if (e instanceof ApiError && [401, 403].includes(e.status)) { setData(null); setEditing(false) }
      setError(e instanceof Error ? e.message : 'Save could not be confirmed. Reload access before trying again.')
    } finally { setBusy(false) }
  }
  function closeEditor() {
    if (!leave()) return
    setEditing(false); setChoosing(false); setSelected([]); setId(''); setRemove(null)
    requestAnimationFrame(() => document.getElementById('access-list-title')?.focus())
  }
  function choose(next: string) {
    if (!leave()) return
    setId(next); setSelected(data?.grants.find(grant => grant.kind === kind && grant.id === next)?.permissions || [])
  }
  const picked = members.find(member => member.id === id || member.value === id)
  const title = current?.display_name || picked?.display_name || (kind === 'role' ? roles.find(role => role.id === id)?.name : '') || (current?.label !== id ? current?.label : '') || 'Identity unavailable'
  const username = current?.username || picked?.username
  const matches = data?.grants.filter(grant => [grant.display_name, grant.username, grant.label, grant.id].join(' ').toLowerCase().includes(search.toLowerCase())) || []
  const labels = Object.fromEntries(data?.groups.flatMap(g => g.permissions.map(p => [p.id, p.label])) || [])
  return <div className={`access-workspace ${editing ? 'access-editing' : ''}`}>
    <div className="page-head"><div><p className="eyebrow">Owner controls</p><h1>Dashboard access</h1><p>Select a person or role, choose what they can do, then save.</p></div></div>
    <div className="access-toolbar"><span>{data ? `${data.grants.length} access entries · 2 protected owners` : 'Staff permissions'}</span><button disabled={busy || loading} onClick={() => { if (leave()) { setEditing(false); setSelected([]); setId(''); void load() } }}>Refresh access</button></div>
    {error && <div className="notice error" role="alert">{error} Use Refresh access to check saved permissions.</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {loading && <p role="status">Loading access…</p>}
    {data && <div className="access-layout">
      <section className="access-directory" aria-label="People and roles">
        <h2 id="access-list-title" tabIndex={-1}>People &amp; roles</h2>
        <button className="primary" disabled={busy || loading} onClick={() => edit()}>+ Add access</button>
        <label>Find existing access<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, username or ID" /></label>
        {!matches.length && <p>{data.grants.length ? 'No matching entries.' : 'No added staff yet. Choose Add access to get started.'}</p>}
        {matches.map(grant => <button className="access-person" key={`${grant.kind}:${grant.id}`} disabled={busy || loading} aria-pressed={editing && kind === grant.kind && id === grant.id} onClick={() => edit(grant)}>
          <AccessAvatar name={grant.display_name || grant.label} kind={grant.kind} url={grant.avatar_url} /><span className="access-person-info"><strong>{grant.display_name || (grant.label !== grant.id ? grant.label : 'Unresolved '+(grant.kind === 'role' ? 'role' : 'member'))}</strong>
          <small>{grant.kind === 'role' ? 'Role' : 'Member'}{grant.username ? ` · @${grant.username}` : ''}</small>
          <small>{grant.permissions.length} {grant.permissions.length === 1 ? 'action' : 'actions'} · {grant.kind === 'role' ? 'Role ID' : 'Discord ID'}: {grant.id}</small></span>
        </button>)}
        <details><summary>Protected owners</summary><p>Only these two owners can change access. Ownership cannot be granted here.</p>{data.owners.map(owner => <p key={owner}>Discord ID: <code>{owner}</code></p>)}</details>
      </section>
      <section className="access-editor" aria-label="Permission editor">
        {!editing ? <div className="access-empty"><h2>Choose whose access to manage</h2><p>Select an existing person or role, or add someone by searching their Discord name.</p><p>CWL covers Main and Lazy. Clan management applies to all family clans.</p></div> : <>
          <button className="access-back" disabled={busy} onClick={closeEditor}>← Back to people &amp; roles</button>
          <h2 ref={heading} tabIndex={-1}>{choosing ? 'Choose a person or role' : title}</h2>
          {choosing ? <>
            <fieldset disabled={busy}><legend>Who gets access?</legend><div className="access-subject">
              <label><input type="radio" checked={kind === 'user'} onChange={() => { if (leave()) { setKind('user'); setId(''); setSelected([]) } }} />Person</label>
              <label><input type="radio" checked={kind === 'role'} onChange={() => { if (leave()) { setKind('role'); setId(''); setSelected([]) } }} />Discord role</label>
            </div></fieldset>
            {kind === 'user' ? <MemberPicker label="Staff member" value={id} disabled={busy} showRoles={false} onOptions={rows => setMembers(old => [...new Map([...old,...rows].map(row => [row.id,row])).values()])} onChange={value => choose(String(value || ''))} /> : <div className="access-role-picker">
              <label>Search roles<input type="search" value={roleSearch} onChange={event => setRoleSearch(event.target.value)} placeholder="Type a role name" /></label>
              {roleError ? <div role="alert">{roleError}<button onClick={() => setRoleReload(value => value + 1)}>Retry roles</button></div> : <div className="access-role-results">{roles.filter(role => role.name.toLowerCase().includes(roleSearch.toLowerCase())).map(role => <button key={role.id} aria-pressed={id === role.id} onClick={() => choose(role.id)}><strong>{role.name}</strong><small>Role ID: {role.id}</small></button>)}{rolesLoading && <p role="status">Loading roles…</p>}{!rolesLoading && !roles.length && <p>No available roles.</p>}{!!roles.length && !roles.some(role => role.name.toLowerCase().includes(roleSearch.toLowerCase())) && <p>No matching roles.</p>}</div>}
            </div>}
            {id && <p>Selected: <strong>{title}</strong> · {id}</p>}
            {kind === 'user' && data.owners.includes(id) && <p role="status">This is a protected owner. Their access cannot be edited.</p>}
            <button className="primary" disabled={!id || busy || (kind === 'role' && (rolesLoading || !!roleError)) || (kind === 'user' && data.owners.includes(id))} onClick={() => { setChoosing(false); requestAnimationFrame(() => heading.current?.focus()) }}>Choose permissions →</button>
          </> : <>
            <div className="access-identity-header"><AccessAvatar name={title} kind={kind} url={current?.avatar_url || picked?.avatar_url} /><p className="access-identity">{kind === 'role' ? 'Discord role' : 'Specific member'}{username ? ` · @${username}` : ''}<br />{kind === 'role' ? 'Role ID' : 'Discord ID'}: <code>{id}</code></p></div>
            {current && current.identity_status !== 'current' && <p className="inline-reason">{current.identity_status === 'missing' ? 'Not found in this server. Saved access remains until removed.' : 'Live identity unavailable. Refresh access to retry.'}</p>}
            {kind === 'user' && <a href={`https://discord.com/users/${id}`} target="_blank" rel="noreferrer">Open Discord profile ↗</a>}
            <p>CWL includes Main and Lazy. Clan permissions apply to all clans. User and role grants add together.</p>
            <AccessPermissions groups={data.groups} selected={selected} disabled={busy || loading} onChange={setSelected} />
            <p className="small">Access management stays owner-only. Section controls grant only the actions currently listed.</p>
            {current && <button disabled={busy || dirty} onClick={() => setRemove(current)}>Remove this access entry</button>}
            {remove && <div className="notice error" role="alert"><p>Remove access for <strong>{title}</strong> ({remove.id})? Other role or user grants still apply.</p><button disabled={busy} onClick={() => setRemove(null)}>Cancel removal</button><button disabled={busy} onClick={() => void save(remove)}>Confirm removal</button></div>}
            <div className="access-savebar"><span role="status">{dirty ? 'Unsaved changes' : 'No unsaved changes'} · {selected.length} {selected.length === 1 ? 'action' : 'actions'}</span><div><button disabled={busy || !dirty} onClick={() => { setSelected(current?.permissions || []); setRemove(null) }}>Reset</button><button className="primary" disabled={busy || loading || !dirty || !selected.length || (kind === 'user' && data.owners.includes(id))} onClick={() => void save()}>{busy ? 'Saving…' : 'Save access'}</button></div>{!selected.length && <small>Select an action to save. To revoke an existing entry, use Remove this access entry.</small>}</div>
          </>}
        </>}
      </section>
    </div>}
    {data && <details className="access-history"><summary>Access history · latest 200 changes</summary>{data.history.length ? [...data.history].reverse().map((row, i) => <p key={i}><strong>{row.after ? 'Saved' : 'Removed'} {row.after?.label || row.before?.label || row.subject_id}</strong><br /><small>{new Date(row.at).toLocaleString()} · Owner {row.actor_id}</small><br />{row.after?.permissions.map(p => labels[p] || p).join(' · ') || 'Entry removed'}</p>) : <p>No changes recorded yet.</p>}</details>}
  </div>
}
