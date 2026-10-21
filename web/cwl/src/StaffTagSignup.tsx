import useUnsavedWork from './useUnsavedWork'
import {useEffect,useRef,useState} from 'react'
import {api,type Account,type Pool} from './api'
import MemberPicker from './MemberPicker'
import TownHallIcon from './TownHallIcon'
type Lookup={account:Account;linked_user_id:string|null;signed_up_pool:Pool|null}
export default function StaffTagSignup({seasonId,onSaved,onDirty,onBusy}:{seasonId:string;onSaved:()=>Promise<void>;onDirty:(dirty:boolean)=>void;onBusy:(busy:boolean)=>void}){
 const [tag,setTag]=useState(''),[result,setResult]=useState<Lookup|null>(null),[hasDiscord,setHasDiscord]=useState(false),[uid,setUid]=useState(''),[searchMember,setSearchMember]=useState(false),[pool,setPool]=useState<Pool|''>(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false)
 useUnsavedWork(!saved && !!tag.trim(),onDirty)
 useEffect(()=>{onBusy(busy);return()=>onBusy(false)},[busy,onBusy])
 const sequence=useRef(0)
 async function lookup(){const turn=++sequence.current;setBusy(true);setError('');setResult(null);setSaved(false)
  try{const data=await api<Lookup>(`/seasons/${seasonId}/staff-signups/player?tag=${encodeURIComponent(tag.trim())}`);if(turn!==sequence.current)return;setResult(data);setUid(data.linked_user_id||'');setHasDiscord(!!data.linked_user_id);setSearchMember(false);setPool('')}
  catch(e){if(turn===sequence.current)setError(e instanceof Error?e.message:'Could not find this player.')}
  finally{if(turn===sequence.current)setBusy(false)}
 }
 async function add(){if(!result||!pool||busy)return;setBusy(true);setError('')
  try{await api(`/seasons/${seasonId}/staff-signups/player`,'POST',{tag:result.account.tag,pool,prefer_crystal_1_or_lower:false,has_discord:hasDiscord,user_id:hasDiscord?uid.trim():'',expected_linked_user_id:result.linked_user_id});setSaved(true);try{await onSaved()}catch{setError('Signup saved. Refresh the page to update the roster.')}}
  catch(e){setError(e instanceof Error?e.message:'Could not add signup.')}
  finally{setBusy(false)}
 }
 return <div className="staff-tag-signup"><p>Enter a player tag. We’ll check for a linked Discord account.</p><div className="staff-tag-lookup"><label>Player tag<input value={tag} disabled={busy} placeholder="#ABC123" maxLength={20} onChange={e=>{setTag(e.target.value);setResult(null);setSaved(false);setError('')}} onKeyDown={e=>{if(e.key==='Enter'&&tag.trim()){e.preventDefault();void lookup()}}}/></label><button disabled={busy||!tag.trim()} onClick={()=>void lookup()}>{busy&&!result?'Checking…':'Find player'}</button></div>
 {result&&<div className="staff-tag-result"><div className="staff-tag-player"><TownHallIcon level={result.account.town_hall}/><div><strong>{result.account.name}</strong><small>{result.account.tag} · {result.account.current_clan_name||'No clan'}</small></div></div>{saved?<p className="notice success" role="status">Signup added. Use Roster builder to assign a clan.</p>:result.signed_up_pool?<p className="notice" role="status">Already signed up for {result.signed_up_pool==='main'?'Main':'Lazy'} CWL. Open Manage account in Saved signups to change its clan placement.</p>:<fieldset disabled={busy}>
 {result.linked_user_id?<p>✓ Linked Discord account found: <strong>{result.linked_user_id}</strong></p>:<><label className="check-label"><input type="checkbox" checked={hasDiscord} onChange={e=>{setHasDiscord(e.target.checked);setUid('');setSearchMember(false)}}/>Has a Discord account</label>{!hasDiscord&&<p className="small">No Discord link found. You can add this player without Discord.</p>}</>}
 {hasDiscord&&!result.linked_user_id&&<><label>Discord ID<input inputMode="numeric" placeholder="Enter Discord user ID" value={uid} onChange={e=>setUid(e.target.value)} maxLength={22}/></label><button type="button" onClick={()=>setSearchMember(v=>!v)} aria-expanded={searchMember}>{searchMember?'Hide member search':'Find a server member'}</button>{searchMember&&<MemberPicker label="Discord account for signup" value={uid} onChange={v=>setUid(String(v||''))} disabled={busy} endpoint="/staff-signup-members" showRoles={false}/>}<p className="small">This connects the member to this signup only.</p></>}
 <label>CWL type<select value={pool} onChange={e=>setPool(e.target.value as Pool|'')}><option value="">Choose Main or Lazy</option><option value="main">Main CWL</option><option value="lazy">Lazy CWL</option></select></label>
 <button className="primary" disabled={busy||!pool||(hasDiscord&&!/^\d{15,22}$/.test(uid.trim()))} onClick={()=>void add()}>{busy?'Saving…':'Add signup'}</button>
 </fieldset>}</div>}{error&&<p className="notice error" role="alert">{error}</p>}</div>
}
