import {useState} from 'react'
import {api} from './api'
type Entry={id:string;member:string;role:string;action:string;status:string;at:string}
export default function CommandActivity({command}:{command:string}){
 const [rows,setRows]=useState<Entry[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 async function load(){setBusy(true);try{setRows((await api<{events:Entry[]}>('/manage/text-command-activity?command='+encodeURIComponent(command))).events);setError('')}catch{setError('Could not load role activity.')}finally{setBusy(false)}}
 return <details className="command-activity" onToggle={e=>{if(e.currentTarget.open)void load()}}><summary>Role changes from this trigger</summary><p className="small">Roles added or removed by this trigger’s buttons. Pings do not appear here.</p><button type="button" disabled={busy} onClick={()=>void load()}>{busy?'Loading…':'Refresh activity'}</button>{error&&<p role="alert">{error}</p>}{!busy&&!error&&!rows.length&&<p>No role actions yet.</p>}<div>{rows.map(row=><article key={row.id}><strong>{row.member}</strong><span>{row.action==='add_role'?'Add':'Remove'} · {row.role}</span><small>{row.status==='done'?'Completed':row.status==='failed'?'Failed':'Unconfirmed'} · {new Date(row.at).toLocaleString()}</small></article>)}</div></details>
}
