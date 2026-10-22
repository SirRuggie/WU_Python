import useUnsavedWork from './useUnsavedWork'
import StaffPlayerButton from './StaffPlayerButton'
import StaffTagSignup from './StaffTagSignup'
import {useEffect,useRef,useState} from 'react'
import {api,type Account,type Pool,type Season} from './api'
import MemberPicker from './MemberPicker'
import TownHallIcon from './TownHallIcon'
import './StaffSignupControls.css'
type Choice=Account&{signed_up_pool:Pool|null}
export default function StaffSignupControls({season,onChanged,onDirty,onBusy}:{season:Season;onChanged:(added:boolean)=>Promise<void>;onDirty:(dirty:boolean)=>void;onBusy:(busy:boolean)=>void}){
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[uid,setUid]=useState(''),[pool,setPool]=useState<Pool|''>(''),[accounts,setAccounts]=useState<Choice[]>([]),[selected,setSelected]=useState<string[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[reload,setReload]=useState(0)
 const [mode,setMode]=useState<'tag'|'member'>('member')
 const [search,setSearch]=useState(''),[tagDirty,setTagDirty]=useState(false),[tagBusy,setTagBusy]=useState(false)
 const [editorDirty,setEditorDirty]=useState(false),[editorBusy,setEditorBusy]=useState(false)
 const dirty=editorDirty || open && (!!uid || !!pool || selected.length>0 || tagDirty)
 const working=busy || tagBusy || editorBusy
 useUnsavedWork(dirty || working,onDirty)
 useEffect(()=>{onBusy(working);return()=>onBusy(false)},[working,onBusy])
 const canDiscard=()=>!working && (!dirty || window.confirm('Discard this unfinished signup? Saved signups will stay unchanged.'))
 const addButton=useRef<HTMLButtonElement>(null)
 const restoreAddFocus=()=>requestAnimationFrame(()=>addButton.current?.focus({preventScroll:true}))
 const reset=()=>{setUid('');setPool('');setSelected([]);setSearch('');setTagDirty(false);setOpen(false)}
 const close=()=>{reset();restoreAddFocus()}
 const matching=accounts.filter(account=>[account.name,account.tag,account.current_clan_name].some(value=>value?.toLowerCase().includes(search.trim().toLowerCase())))
 const unsigned=matching.filter(account=>!account.signed_up_pool)
 const heading=useRef<HTMLHeadingElement>(null)
 const archived=season.status==='archived'
 useEffect(()=>{if(open)heading.current?.focus()},[open])
 useEffect(()=>{let active=true;setAccounts([]);setError('');if(!uid){setLoading(false);return}setLoading(true);api<{accounts:Choice[]}>(`/seasons/${season.id}/staff-signups/accounts?user_id=${encodeURIComponent(uid)}`).then(data=>{if(active){setAccounts(data.accounts);setSelected(current=>current.filter(tag=>data.accounts.some(account=>account.tag===tag&&!account.signed_up_pool)))}}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[uid,season.id,reload])
 async function toggle(){
  if(busy||archived)return
  const action=season.signup_open?'Close':'Open'
  if(!window.confirm(`${action} Main and Lazy signups for ${season.label}? Existing signups will stay saved.`))return
  setBusy(true);setError('');setNotice('')
  try{await api(`/seasons/${season.id}`,'PATCH',{signup_open:!season.signup_open});setNotice(`Signups ${season.signup_open?'closed':'opened'}.`);await onChanged(false)}catch(e){setError(e instanceof Error?e.message:'Could not change signups.')}finally{setBusy(false)}
 }
 async function add(){
  if(busy||loading||error||!uid||!pool||!selected.length||archived)return
  if(!window.confirm(`Add ${selected.length} accounts to ${pool==='main'?'Main':'Lazy'} CWL for the selected member?`))return
  setBusy(true);setError('');setNotice('')
  try{
   const result=await api<{count:number}>(`/seasons/${season.id}/staff-signups`,'POST',{user_id:uid,pool,accounts:selected.map(tag=>({tag,prefer_crystal_1_or_lower:false}))})
   setSelected([]);setOpen(false);setUid('');setPool('');setNotice(`${result.count} account${result.count===1?'':'s'} added to ${pool==='main'?'Main':'Lazy'} CWL. Use Roster builder to assign a clan.`)
   try{await onChanged(true)}catch{setError('Signup saved. Refresh the page to see the latest list.')}
   restoreAddFocus()
  }catch(e){setError(e instanceof Error?e.message:'Could not add signup.')}finally{setBusy(false)}
 }
 return <section className="staff-signup-controls" aria-label="Staff signup controls"><div className="staff-signup-bar"><div><strong>{archived?'Season archived':season.signup_open?'Signups open':'Signups closed'}</strong><small>Main and Lazy CWL · {archived?'View only':season.signup_open?'Members can sign up.':'Only staff can add signups.'}</small></div><div className="staff-signup-actions"><button disabled={working||archived} onClick={()=>void toggle()}>{season.signup_open?'Close signups':'Open signups'}</button><button ref={addButton} className="primary" disabled={working||archived} aria-expanded={open} onClick={()=>{if(open){if(canDiscard())close()}else setOpen(true)}}>Add signup</button></div></div>
 {notice&&<p className="notice success" role="status">{notice}</p>}
 {open&&<div className="staff-signup-form"><div className="section-heading"><h2 ref={heading} tabIndex={-1}>Add signup</h2><button disabled={working} onClick={()=>{if(canDiscard())close()}}>Cancel</button></div><div className="workflow-tabs staff-add-modes" role="group" aria-label="How to add signup"><button aria-pressed={mode==='tag'} disabled={working} onClick={()=>{if(mode!=='tag'&&canDiscard()){reset();setOpen(true);setMode('tag')}}}>By player tag</button><button aria-pressed={mode==='member'} disabled={working} onClick={()=>{if(mode!=='member'&&canDiscard()){reset();setOpen(true);setMode('member')}}}>By Discord member</button></div>{mode==='tag'?<StaffTagSignup seasonId={String(season.id)} onSaved={()=>onChanged(true)} onDirty={setTagDirty} onBusy={setTagBusy}/>:<><p>Choose a member and their linked accounts.</p><fieldset disabled={busy}><MemberPicker label="Member for signup" value={uid} onChange={value=>{if(selected.length&&!window.confirm('Change member and clear selected accounts?'))return;setUid(String(value||''));setSelected([]);setSearch('')}} disabled={busy} endpoint="/staff-signup-members" showRoles={false}/>
 {uid&&<><label>CWL type<select value={pool} onChange={e=>setPool(e.target.value as Pool|'')}><option value="">Choose Main or Lazy</option><option value="main">Main CWL</option><option value="lazy">Lazy CWL</option></select></label><div className="section-heading"><h3>Linked accounts</h3><button type="button" disabled={loading||busy} onClick={()=>setReload(n=>n+1)}>Reload accounts</button></div>{loading?<p role="status">Loading accounts…</p>:!accounts.length?<p>{error?'Could not load accounts. Select Reload accounts to try again.':'No linked accounts. Ask this member to use /link in Discord, then reload accounts.'}</p>:<><div className="staff-signup-list-tools"><label>Find an account<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Account name, tag or clan"/></label></div>
 <div className="staff-signup-list-tools"><label className="check-label"><input type="checkbox" checked={unsigned.length>0&&unsigned.every(account=>selected.includes(account.tag))} ref={node=>{if(node)node.indeterminate=unsigned.some(account=>selected.includes(account.tag))&&!unsigned.every(account=>selected.includes(account.tag))}} disabled={!unsigned.length||loading} onChange={event=>setSelected(current=>event.target.checked?[...new Set([...current,...unsigned.map(account=>account.tag)])]:current.filter(tag=>!unsigned.some(account=>account.tag===tag)))}/>Select all matching accounts ({unsigned.length})</label><button disabled={!selected.length} onClick={()=>setSelected([])}>Clear selection</button></div>
 {!matching.length&&<p>No accounts match your search.</p>}<div className="staff-signup-accounts">{matching.map(a=><div className="staff-signup-account" key={a.tag}><label><input type="checkbox" disabled={!!a.signed_up_pool||busy} checked={selected.includes(a.tag)} onChange={e=>setSelected(old=>e.target.checked?[...old,a.tag]:old.filter(tag=>tag!==a.tag))}/><TownHallIcon level={a.town_hall}/><span><strong>{a.name}</strong><small>{a.tag} · {a.current_clan_name||'No clan'}</small>{a.signed_up_pool&&<small>Already signed up · {a.signed_up_pool==='main'?'Main':'Lazy'} CWL</small>}</span></label>{a.signed_up_pool&&<StaffPlayerButton onDirty={setEditorDirty} onBusy={setEditorBusy} seasonId={String(season.id)} tag={a.tag} onChanged={async()=>{setReload(n=>n+1);await onChanged(true)}}>Manage signup</StaffPlayerButton>}</div>)}</div></>}
 <div className="staff-signup-submit"><strong>{selected.length} selected{pool?` · ${pool==='main'?'Main':'Lazy'} CWL`:''}</strong><button className="primary" disabled={busy||loading||!!error||!pool||!selected.length} onClick={()=>void add()}>{busy?'Saving…':`Add ${selected.length||''} ${selected.length===1?'account':'accounts'}`}</button></div></>}
 </fieldset></>}</div>}{error&&<p className="notice error" role="alert">{error}</p>}</section>
}
