import type {RosterClan} from './roster'
export default function ClanDestinationOptions({clans,current}:{clans:RosterClan[];current?:string|null}){
 return <>{(['main','lazy',null] as const).map(pool=>{const group=clans.filter(c=>!c.archived&&c.pool===pool);return group.length?<optgroup key={pool||'unset'} label={pool==='main'?'Main CWL':pool==='lazy'?'Lazy CWL':'Group not set'}>{group.map(c=><option key={c.tag} value={c.tag} disabled={c.assigned_count>=c.effective_capacity&&c.tag!==current}>{c.name} · {c.assigned_count}/{c.effective_capacity}{c.assigned_count>=c.effective_capacity?' · Full':''}</option>)}</optgroup>:null})}</>
}
