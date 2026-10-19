import { useEffect, useState } from 'react'
import { api, type Grant } from './api'
import MemberPicker from './MemberPicker'

type Permission = { id: string; label: string; description: string }
export default function AccessSettings() {
  const [grants, setGrants] = useState<Grant[]>([])
  const [options, setOptions] = useState<Permission[]>([])
  const [userId, setUserId] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  async function load() {
    const result = await api<{grants: Grant[]; permissions: Permission[]}>('/access')
    setGrants(result.grants); setOptions(result.permissions)
  }
  useEffect(() => { void load().catch(e => setError(String(e.message || e))) }, [])
  async function save() {
    setBusy(true); setError(''); setNotice('')
    try {
      await api('/access', 'POST', { user_id: userId.trim(), permissions: selected })
      await load(); setNotice('Access saved. Only the selected areas are allowed.'); setUserId(''); setSelected([])
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save access.') }
    finally { setBusy(false) }
  }
  return <><div className="page-head"><div><p className="eyebrow">Owner controls</p><h1>Dashboard access</h1><p>Choose what each person can manage. Only owners can change access.</p></div></div>
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load().catch(e => setError(e.message))}>Retry</button></div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="card access-card"><h2>{grants.some(g => g.user_id === userId.trim()) ? 'Edit access' : 'Add staff access'}</h2>
      <form onSubmit={e => { e.preventDefault(); void save() }}>
        <MemberPicker label="Staff member" value={userId} disabled={busy} onChange={value => { const id = String(value || ""); setUserId(id); setSelected(grants.find(g => g.user_id === id)?.permissions || []); setNotice('') }} />
        <fieldset disabled={busy}><legend>Allowed areas</legend>
          {options.map(option => <label key={option.id} className="staff-row" style={{justifyContent:'flex-start', gap:12}}>
            <input type="checkbox" checked={selected.includes(option.id)} onChange={e => setSelected(current => e.target.checked ? [...current, option.id] : current.filter(id => id !== option.id))} />
            <span><strong>{option.label}</strong><small style={{display:'block'}}>{option.description}</small></span>
          </label>)}
        </fieldset>
        <p className="small">Server tool access does not grant CWL access or change Discord roles. Discord role limits still apply.</p>
        <button className="primary" disabled={busy || !userId || !selected.length}>Save access</button>
        {userId && <button type="button" disabled={busy} onClick={() => {setUserId(''); setSelected([])}}>Cancel</button>}
      </form></section>
    <section className="card"><h2>Staff access</h2>{grants.length ? grants.map(grant => <div className="staff-row" key={grant.user_id}><div><strong>{grant.username || grant.user_id}</strong><small style={{display:'block'}}>{(grant.permissions || []).map(id => options.find(o => o.id === id)?.label || id).join(' · ')}</small></div><div>
      <button disabled={busy} onClick={() => {setUserId(grant.user_id); setSelected(grant.permissions || []); setNotice(''); window.scrollTo({top:0, behavior:'smooth'})}}>Edit access</button>
      <button className="danger-link" disabled={busy} onClick={async () => { if (!window.confirm('Remove all dashboard staff access for this person?')) return; setBusy(true); try { await api(`/access/${encodeURIComponent(grant.user_id)}`, 'DELETE'); await load(); if(userId === grant.user_id){setUserId('');setSelected([])}; setNotice('Staff access removed.') } catch(e) {setError(e instanceof Error ? e.message : 'Could not remove access.')} finally {setBusy(false)} }}>Remove access</button>
    </div></div>) : <p>No added staff.</p>}</section></>
}
