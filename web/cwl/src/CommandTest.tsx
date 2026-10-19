import {useState} from 'react'
import {api} from './api'
import ChannelCombobox from './ChannelCombobox'
import type {AnnouncementChannel} from './announcements'
import type {Command} from './CommandBuilder'
const requestId=()=>crypto.randomUUID().replaceAll('-','').slice(0,24)
export default function CommandTest({draft,disabled}:{draft:Command;disabled:boolean}){
 const [channels,setChannels]=useState<AnnouncementChannel[]>([]),[channel,setChannel]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[url,setUrl]=useState(''),[nonce,setNonce]=useState(requestId)
 async function load(){try{setChannels((await api<{channels:AnnouncementChannel[]}>('/manage/text-command-test-channels')).channels);setError('')}catch(e){setError(e instanceof Error?e.message:'Could not load channels.')}}
 async function send(){if(!window.confirm(`Send this draft to #${channels.find(c=>c.id===channel)?.name}? Pings and role controls are disabled in tests.`))return;setBusy(true);setError('');setUrl('');try{const result=await api<{url:string}>('/manage/text-command-test','POST',{values:draft,channel_id:channel,request_id:nonce});setUrl(result.url);setNonce(requestId())}catch(e){setError(e instanceof Error?e.message:'Could not confirm delivery. Check the channel.')}finally{setBusy(false)}}
 return <details className="card command-test" onToggle={e=>{if(e.currentTarget.open&&!channels.length)void load()}}><summary>Send test to channel</summary><p className="small">Posts this draft without saving or enabling it. Pings and interactive controls are disabled.</p><ChannelCombobox label="Test channel" channels={channels} value={channel} disabled={disabled||busy} onChange={setChannel}/><button type="button" disabled={disabled||busy||!channel} onClick={()=>void send()}>{busy?'Sending…':'Send test'}</button>{error&&<p role="alert">{error} <button type="button" onClick={()=>void load()}>Reload channels</button></p>}{url&&<p role="status">Test sent. <a href={url} target="_blank" rel="noreferrer">Open in Discord ↗</a></p>}</details>
}
