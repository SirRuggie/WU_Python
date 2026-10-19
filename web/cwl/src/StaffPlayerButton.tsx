import {useEffect,useRef,useState,type ReactNode} from 'react'
import {api,ApiError} from './api'
import type {RosterSnapshot} from './roster'
import RosterPlayerDialog from './RosterPlayerDialog'
export default function StaffPlayerButton({seasonId,tag,children,onChanged,disabled=false}:{seasonId:string;tag:string;children:ReactNode;onChanged?:()=>void|Promise<unknown>;disabled?:boolean}){
 const [snapshot,setSnapshot]=useState<RosterSnapshot|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const generation=useRef(0)
 useEffect(()=>{generation.current++;setSnapshot(null);setError('');setBusy(false);return()=>{generation.current++}},[seasonId,tag])
 const path=`/seasons/${encodeURIComponent(seasonId)}`
 async function open(){const id=++generation.current;setBusy(true);setError('');try{const result=await api<RosterSnapshot>(`${path}/roster`);if(id!==generation.current)return;if(!result.accounts.some(a=>a.tag===tag))throw new Error('This account is no longer signed up in this season.');setSnapshot(result)}catch(e){if(id===generation.current)setError(e instanceof Error?e.message:'Could not load account.')}finally{if(id===generation.current)setBusy(false)}}
 async function write(remove:boolean,body:Record<string,unknown>={}){
  if(!snapshot||busy)return false
  const id=generation.current;setBusy(true);setError('')
  try{
   await api(`${path}/${remove?'staff-signups':'roster'}/${encodeURIComponent(tag)}`,remove?'DELETE':'PATCH',{revision:snapshot.revision,...body})
   if(id!==generation.current)return true
   setSnapshot(null)
   try{await onChanged?.()}catch{setError('Saved. Refresh the page to see the latest list.')}
   return true
  }catch(e){if(id===generation.current){setError(e instanceof Error?e.message:'Could not save account.');if(e instanceof ApiError&&e.status===409){setSnapshot(null);setError('The roster changed. Open the account again to review the latest details.')}}return false}
  finally{if(id===generation.current)setBusy(false)}
 }
 const account=snapshot?.accounts.find(a=>a.tag===tag)
 return <><button type="button" className="roster-player-name" disabled={disabled||busy} onClick={()=>void open()} title="Edit account">{children}</button>{error&&!account&&<small role="alert">{error}</small>}{account&&snapshot&&<RosterPlayerDialog account={account} clans={snapshot.clans} busy={busy} error={error} onClose={()=>{if(!busy)setSnapshot(null)}} onSave={body=>write(false,body)} onRemove={()=>write(true)}/>}</>
}
