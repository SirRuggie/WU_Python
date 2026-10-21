import DashboardIcon from './DashboardIcon'
import { useEffect, useState } from 'react'
import { api, type Account } from './api'
import { pushSupport, getBrowserSubscription, enableBrowserPush, disableBrowserPush } from './webPush'
import TownHallIcon from './TownHallIcon'
import './PushReminders.css'
export type ReminderSubscription = { id: string; enabled: boolean; tags: string[]; war: boolean; cwl: boolean; offsets: number[]; updated_at?: number }
type PushStatus = { available: boolean; public_key: string; subscriptions: ReminderSubscription[] }
type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{outcome:string}> }
export async function subscriptionId(subscription: PushSubscription) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(subscription.endpoint))
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2,'0')).join('')
}
// Explicit sign-out stops this browser's personal reminders, not other devices.
export async function stopPushOnSignout(): Promise<string | null> {
  let id: string | null = null
  try {
    const registration = 'serviceWorker' in navigator ? await navigator.serviceWorker.getRegistration('/') : null
    const subscription = await registration?.pushManager?.getSubscription()
    if (subscription) id = await subscriptionId(subscription)
    await disableBrowserPush()
  } catch { /* Browser failures must not block ending the authenticated session. */ }
  return id
}
export default function PushReminders({ accounts }: { accounts: Account[] }) {
  const support = pushSupport()
  const [status,setStatus] = useState<PushStatus | null>(null)
  const [current,setCurrent] = useState<ReminderSubscription | null>(null)
  const [tags,setTags] = useState<string[]>([])
  const [war,setWar] = useState(true)
  const [cwl,setCwl] = useState(true)
  const [offsets,setOffsets] = useState<number[]>([120])
  const validTimes = offsets.length > 0 && offsets.every(value => value >= 1 && value <= 1440) && new Set(offsets).size === offsets.length
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const [notice,setNotice] = useState('')
  const [search,setSearch] = useState('')
  const [install,setInstall] = useState<InstallEvent | null>(null)
  const load = async () => {
    const result = await api<PushStatus>('/push')
    const browser = await getBrowserSubscription()
    const id = browser ? await subscriptionId(browser) : null
    const saved = result.subscriptions.find(item => item.id === id) || null
    setStatus(result);setCurrent(saved)
    if (saved) {setTags(saved.tags);setWar(saved.war);setCwl(saved.cwl);setOffsets(saved.offsets)}
  }
  useEffect(() => { let live=true; api<PushStatus>('/push').then(async result => { const browser = await getBrowserSubscription(); const id=browser ? await subscriptionId(browser):null; if(!live)return; const saved=result.subscriptions.find(item=>item.id===id)||null; setStatus(result);setCurrent(saved);if(saved){setTags(saved.tags);setWar(saved.war);setCwl(saved.cwl);setOffsets(saved.offsets)} }).catch(cause=>{if(live)setError(cause instanceof Error?cause.message:'Reminder settings unavailable')});const capture=(event:Event)=>{event.preventDefault();setInstall(event as InstallEvent)};window.addEventListener('beforeinstallprompt',capture);return()=>{live=false;window.removeEventListener('beforeinstallprompt',capture)} },[])
  const act = async (work:()=>Promise<void>) => {setBusy(true);setError('');setNotice('');try{await work()}catch(cause){setError(cause instanceof Error?cause.message:'Request failed. Try again.')}finally{setBusy(false)}}
  const enable = () => {
    if (!status?.available || !tags.length || !validTimes || (!war&&!cwl)) return
    // Start permission request on the user's click, before any server request.
    const pending = enableBrowserPush(status.public_key)
    void act(async()=>{const subscription=await pending;const saved=await api<ReminderSubscription>('/push/subscriptions','PUT',{subscription:subscription.toJSON(),enabled:true,tags,war,cwl,offsets});setCurrent(saved);await load();setNotice('Phone reminders are on for this device, grouped by war clan.')})
  }
  const visible=accounts.filter(account=>`${account.name} ${account.tag} ${account.current_clan_name||''}`.toLowerCase().includes(search.trim().toLowerCase()))
  const dirty=!!current&&(JSON.stringify([...tags].sort())!==JSON.stringify([...current.tags].sort())||war!==current.war||cwl!==current.cwl||JSON.stringify([...offsets].sort())!==JSON.stringify([...current.offsets].sort()))
  return <details className="card push-reminders"><summary><span><DashboardIcon name="bell"/> Phone reminders</span><span className="badge">{current?.enabled?'On for this device':'Off for this device'}</span></summary>
    <p>Get one reminder per clan at each chosen time. It lists your selected accounts with attacks left.</p>
    <p className="small">Reminders can arrive while the app is closed. Phone settings, connection issues or delayed game data can affect delivery. Unavailable war data is skipped.</p>
    {install ? <button onClick={()=>void install.prompt().then(()=>install.userChoice).then(()=>setInstall(null))}>Install Warriors United app ↗</button> : <p className="small">Install from your browser menu: Install app / Add to Home Screen. On iPhone, open the Home Screen app before enabling notifications.</p>}
    {!support.supported&&<p className="notice">{support.reason}</p>}{support.permission==='denied'&&<p className="notice">Notifications are blocked. Allow notifications for this site in your browser settings, then return here.</p>}
    {status&&!status.available&&<p className="notice">Phone reminders are not ready yet. Your choices have not been enabled.</p>}
    {error&&<p className="notice error" role="alert">{error}<button disabled={busy} onClick={()=>void act(load)}>Retry settings</button></p>}{notice&&<p className="notice success" role="status">{notice}</p>}
    <fieldset disabled={busy}><legend>Remind me about</legend><div className="push-options"><label><input type="checkbox" checked={war} onChange={event=>setWar(event.target.checked)}/>War</label><label><input type="checkbox" checked={cwl} onChange={event=>setCwl(event.target.checked)}/>CWL</label></div></fieldset>
    <fieldset disabled={busy}><legend>Remind me before war ends</legend>
      <p className="small">Choose hours and minutes. Add up to five different times; each sends one reminder per clan.</p>
      <div className="push-times">{offsets.map((value,index)=><div className="push-time-row" key={index}>
        <span className="push-time-number">{index+1}.</span>
        <label>Hours<select aria-label={`Reminder ${index+1} hours`} value={Math.floor(value/60)} onChange={event=>{const hours=Number(event.target.value);setOffsets(current=>current.map((item,i)=>i===index?hours*60+(hours===24?0:item%60):item))}}>{Array.from({length:25},(_,hour)=><option key={hour} value={hour}>{hour}</option>)}</select></label>
        <label>Minutes<select aria-label={`Reminder ${index+1} minutes`} value={value%60} disabled={value===1440} onChange={event=>setOffsets(current=>current.map((item,i)=>i===index?Math.floor(item/60)*60+Number(event.target.value):item))}>{Array.from({length:60},(_,minute)=><option key={minute} value={minute}>{minute.toString().padStart(2,'0')}</option>)}</select></label>
        <button type="button" aria-label={`Remove reminder ${index+1}`} onClick={()=>setOffsets(current=>current.filter((_,i)=>i!==index))}>Remove</button>
      </div>)}</div>
      {offsets.length<5&&<button type="button" onClick={()=>setOffsets(current=>[...current,[120,30,360,60,15,5].find(value=>!current.includes(value))!])}>＋ Add reminder time</button>}
      {!validTimes&&<p className="notice" role="status">Choose at least one time from 1 minute to 24 hours. Each time must be different.</p>}
    </fieldset>
    <fieldset disabled={busy}><legend>Accounts to include · {tags.length} selected</legend><label>Find an account<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Name, tag or current clan"/></label><div className="push-options"><button type="button" onClick={()=>setTags(accounts.map(account=>account.tag))}>Select all linked accounts</button><button type="button" onClick={()=>setTags([])}>Clear</button></div><div className="push-accounts">{visible.map(account=><label key={account.tag}><input type="checkbox" checked={tags.includes(account.tag)} onChange={event=>setTags(current=>event.target.checked?[...current,account.tag]:current.filter(tag=>tag!==account.tag))}/><TownHallIcon level={account.town_hall}/><span><strong>{account.name}</strong><small>{account.tag} · {account.current_clan_name||'No current clan'}</small></span></label>)}</div>{!accounts.length&&<p>Link your Clash accounts and let Todo load before selecting them here.</p>}</fieldset>
    <p className="small">Reminders use the account’s war clan, even if it has moved. Select and save newly linked accounts to include them.</p>
    <div className="push-actions"><button className="primary" disabled={busy||!status?.available||!support.supported||!tags.length||!validTimes||(!war&&!cwl)} onClick={enable}>{busy?'Working…':current?.enabled?'Save reminder choices':'Enable phone reminders'}</button>{current?.enabled&&<><button disabled={busy||dirty} onClick={()=>void act(async()=>{await api(`/push/subscriptions/${current.id}/test`,'POST',{});setNotice('Test notification accepted by the push service. Check this device’s notifications.')})}>Send test notification</button><button disabled={busy} onClick={()=>void act(async()=>{await api(`/push/subscriptions/${current.id}`,'DELETE');await disableBrowserPush();setCurrent(null);await load();setNotice('Phone reminders are off for this device.')})}>Turn off on this device</button></>}</div>{dirty&&<small>Save your changes before testing.</small>}
    {!!status?.subscriptions.some(item=>item.id!==current?.id)&&<details><summary>Other saved devices</summary><p className="small">Remove a device to stop reminders there.</p>{status.subscriptions.filter(item=>item.id!==current?.id).map((item,index)=><div className="push-device" key={item.id}><span>Device {index+1} · {item.enabled?'On':'Off'}<small>{item.updated_at?`Updated ${new Date(item.updated_at * 1000).toLocaleString()}`:''}</small></span><button disabled={busy} onClick={()=>void act(async()=>{await api(`/push/subscriptions/${item.id}`,'DELETE');await load();setNotice('Reminders removed for that device.')})}>Remove device</button></div>)}</details>}
    <p className="small">Notification text can appear on your lock screen. Signing out here turns off reminders on this browser; other devices keep their own settings.</p>
  </details>
}
