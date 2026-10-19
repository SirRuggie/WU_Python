import {useState} from 'react'
import type {Pool} from './api'
import './CwlPoolTabs.css'
export function useCwlPool(){
 const [pool,setPool]=useState<Pool>(()=>{try{return localStorage.getItem('wu-staff-cwl-pool')==='lazy'?'lazy':'main'}catch{return 'main'}})
 return [pool,(next:Pool)=>{setPool(next);try{localStorage.setItem('wu-staff-cwl-pool',next)}catch{}}] as const
}
export default function CwlPoolTabs({value,onChange,disabled=false}:{value:Pool;onChange:(pool:Pool)=>void;disabled?:boolean}){
 return <div className="cwl-pool-tabs" role="group" aria-label="CWL group">{(['main','lazy'] as const).map(pool=><button key={pool} className={value===pool?'active':''} aria-pressed={value===pool} disabled={disabled} onClick={()=>onChange(pool)}>{pool==='main'?'Main CWL':'Lazy CWL'}</button>)}</div>
}
