import { useDashboardPermission } from './DashboardPermissions'
import useUnsavedWork from './useUnsavedWork'
import ClanDestinationOptions from './ClanDestinationOptions'
import {useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {parseManualWeightK,weightInputText,type RosterAccount,type RosterClan} from './roster'
import DiscordContact from './DiscordContact'
import './RosterPlayerDialog.css'
type Props={onDirty?:(dirty:boolean)=>void;account:RosterAccount;clans:RosterClan[];busy:boolean;error?:string;onClose:()=>void;onSave:(body:Record<string,unknown>)=>Promise<boolean>;onRemove:()=>Promise<boolean>}
export default function RosterPlayerDialog({account,clans,busy,error,onClose,onSave,onRemove,onDirty}:Props){
 const canRoster=useDashboardPermission('cwl_roster'),canSignups=useDashboardPermission('cwl_signups')
 const ref=useRef<HTMLDialogElement>(null)
 const [weight,setWeight]=useState(weightInputText(account.manual_weight))
 const [clan,setClan]=useState(account.assigned_clan_tag||'')
 const [kept,setKept]=useState(account.kept)
 const [localError,setLocalError]=useState('')
 const dirty=weight!==weightInputText(account.manual_weight)||clan!==(account.assigned_clan_tag||'')||kept!==account.kept
 useUnsavedWork(dirty||busy,onDirty)
 const close=()=>{if(!busy&&(!dirty||window.confirm('Discard unsaved account changes?')))onClose()}
 useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close()},[])
 async function save(){
  try{
   const body:Record<string,unknown>={}
   const value=parseManualWeightK(weight)
   if(value!==account.manual_weight)body.manual_weight=value
   if(clan!==(account.assigned_clan_tag||''))body.assigned_clan_tag=clan||null
   if(kept!==account.kept||clan!==(account.assigned_clan_tag||''))body.kept=kept
   if(!Object.keys(body).length){onClose();return}
   setLocalError('');if(await onSave(body))onClose()
  }catch(e){setLocalError(e instanceof Error?e.message:'Could not save changes.')}
 }
 async function remove(){if(!window.confirm(`Remove ${account.player_name} from this season's signups and working roster? Published rosters stay unchanged until you publish again.`))return;if(await onRemove())onClose()}
 return createPortal(<dialog className="roster-player-dialog" ref={ref} onCancel={e=>{e.preventDefault();if(!busy)close()}} aria-labelledby="roster-player-title"><header><h2 id="roster-player-title">{account.player_name}</h2><button type="button" disabled={busy} onClick={close}>Close ×</button></header><small>{account.tag} · TH {account.town_hall??'—'} · {account.pool==='main'?'Main':'Lazy'} CWL</small><DiscordContact userId={account.user_id}/><form onSubmit={e=>{e.preventDefault();void save()}}><fieldset disabled={busy || !canRoster}><label>Manual weight (k)<input type="number" inputMode="decimal" min="0" step="0.001" value={weight} onChange={e=>setWeight(e.target.value)} placeholder="Use source weight"/></label><small>Saved for future seasons. Leave blank to use source weight.</small><label>Hosting clan<select value={clan} onChange={e=>{setClan(e.target.value);setKept(true)}}><option value="">Not assigned</option>{account.assigned_clan_tag&&clans.find(c=>c.tag===account.assigned_clan_tag)?.archived&&<option value={account.assigned_clan_tag}>Archived clan · {account.assigned_clan_tag}</option>}<ClanDestinationOptions clans={clans} current={account.assigned_clan_tag}/></select></label><label className="check-label"><input type="checkbox" checked={kept} onChange={e=>setKept(e.target.checked)}/>Keep this placement</label><small>Auto-place will leave this account unchanged.</small>{(localError||error)&&<p role="alert">{localError||error}</p>}<button className="primary" type="submit">{busy?'Saving…':'Save changes'}</button></fieldset></form><small>Changes apply to the working roster. Publish again to update the published roster.</small><div className="roster-player-remove"><button className="danger" disabled={busy || !canSignups} onClick={()=>void remove()}>Remove signup</button><small>Removes this season’s signup and placement. Saved weights stay.</small></div></dialog>,document.body)
}
