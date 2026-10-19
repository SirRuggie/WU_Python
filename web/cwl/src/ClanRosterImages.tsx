import {useEffect,useState} from 'react'
import {api} from './api'
import ChannelCombobox from './ChannelCombobox'
import type {AnnouncementChannel} from './announcements'
import AnnouncementPreviewDialog from './AnnouncementPreviewDialog'
type Clan={tag:string;name:string;pool:string;count:number;pages:number}
type Data={version:number;season:string;clans:Clan[]}
export default function ClanRosterImages({seasonId,version}:{seasonId:string;version:number|null}){
 const [data,setData]=useState<Data|null>(null),[tag,setTag]=useState(''),[channel,setChannel]=useState(''),[channels,setChannels]=useState<AnnouncementChannel[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[url,setUrl]=useState(''),[expanded,setExpanded]=useState(false),[loaded,setLoaded]=useState(false),[nonce,setNonce]=useState('')
 const [refresh,setRefresh]=useState(0)
 const path=`/seasons/${encodeURIComponent(seasonId)}/roster-images`
 useEffect(()=>{let active=true;setData(null);setTag('');setUrl('');setError('');setLoaded(false);if(!version)return
  void Promise.all([api<Data>(path),api<{channels:AnnouncementChannel[]}>('/announcement-channels')]).then(([result,choices])=>{if(active){setData(result);setTag(result.clans[0]?.tag||'');setChannels(choices.channels)}}).catch(e=>{if(active)setError(e.message)})
  return()=>{active=false}
 },[seasonId,version,refresh])
 const clan=data?.clans.find(c=>c.tag===tag)
 function changed(){setLoaded(false);setNonce('');setUrl('');setError('')}
 const imageUrl=(page:number)=>`/api/cwl${path}/${encodeURIComponent(tag)}.png?version=${data?.version}&page=${page}`
 async function send(){
  if(!clan||!data||!channel||busy)return
  if(!window.confirm(`Send only ${clan.name} (${clan.pages} image${clan.pages===1?'':'s'}) to #${channels.find(c=>c.id===channel)?.name||channel}? No pings.`))return
  setBusy(true);setError('');setUrl('')
  const id=nonce||Array.from(crypto.getRandomValues(new Uint8Array(12)),b=>b.toString(16).padStart(2,'0')).join('');setNonce(id)
  try{const result=await api<{url:string}>(`${path}/${encodeURIComponent(tag)}/test`,'POST',{version:data.version,channel_id:channel,request_id:id});setUrl(result.url)}catch(e){setError(e instanceof Error?e.message:'Could not send test. Check Discord before retrying.')}finally{setBusy(false)}
 }
 const pictures=clan?Array.from({length:clan.pages},(_,i)=><div key={`${tag}:${data?.version}:${i}`}><img src={imageUrl(i+1)} alt={`${clan.name} finalized roster, page ${i+1}`} style={{display:'block',width:'100%',height:'auto',borderRadius:8}} onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setError('Image unavailable. Refresh this section.')}}/><a className="button" href={imageUrl(i+1)} download={`roster-${tag.slice(1)}-${i+1}.png`}>Download{clan.pages>1?` page ${i+1}`:' image'}</a></div>):null
 return <section className="card" style={{marginTop:24}}><div className="card-heading"><h2>Clan roster images</h2><button disabled={busy} onClick={()=>setRefresh(n=>n+1)}>Refresh images</button></div><p>Choose a clan, preview its finalized roster, then send a test.</p>{!version?<p>Finalize a roster first.</p>:<><label>Clan<select value={tag} disabled={busy||!data} onChange={e=>{setTag(e.target.value);changed()}}>{!data&&<option>Loading…</option>}{(['main','lazy'] as const).map(pool=><optgroup label={pool==='main'?'Main CWL':'Lazy CWL'} key={pool}>{data?.clans.filter(c=>c.pool===pool).map(c=><option key={c.tag} value={c.tag}>{c.name} · {c.count} players</option>)}</optgroup>)}</select></label>{clan&&<><p className="small">Finalized version {data?.version} · {clan.pages} image{clan.pages===1?'':'s'}. Draft changes are not included.</p><details><summary>Image preview</summary><div style={{maxWidth:480,margin:'12px auto',display:'grid',gap:16}}>{pictures}</div><button onClick={()=>setExpanded(true)}>Expand preview</button></details>{expanded&&<AnnouncementPreviewDialog title={clan.name} onClose={()=>setExpanded(false)}>{pictures}</AnnouncementPreviewDialog>}<ChannelCombobox label="Test channel" channels={channels} value={channel} disabled={busy} onChange={value=>{setChannel(value);setNonce('');setUrl('')}}/><p className="small">Sends only this clan. No pings. Does not mark announcements as sent.</p><button className="primary" disabled={busy||!channel||!loaded||!!url} onClick={()=>void send()}>{busy?'Sending…':'Send test image'}</button>{url&&<p role="status">Test sent. <a href={url} target="_blank" rel="noopener noreferrer">View in Discord ↗</a></p>}</>}{data&&!data.clans.length&&<p>No assigned clans in the finalized roster.</p>}</>}{error&&<p role="alert">{error}</p>}</section>
}
