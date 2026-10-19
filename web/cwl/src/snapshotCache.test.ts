import { expect, it } from 'vitest'
import { readSnapshot, writeSnapshot } from './snapshotCache'
it('isolates user/season snapshots and rejects expired or future data', () => {
 const values = new Map<string,string>()
 const storage = {getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value)}}
 const valid = (v:unknown): v is {count:number} => typeof (v as {count:number})?.count==='number'
 writeSnapshot('home:one:1',{count:2},storage,1000)
 expect(readSnapshot('home:one:1',valid,storage,2000)).toEqual({count:2})
 expect(readSnapshot('home:two:1',valid,storage,2000)).toBeNull()
 expect(readSnapshot('home:one:2',valid,storage,2000)).toBeNull()
 expect(readSnapshot('home:one:1',valid,storage,302000)).toBeNull()
 expect(readSnapshot('home:one:1',valid,storage,999)).toBeNull()
})
it('ignores malformed data and storage failures',()=>{
 const valid=(v:unknown):v is string=>typeof v==='string'
 expect(readSnapshot('x',valid,{getItem:()=>'{'})).toBeNull()
 expect(readSnapshot('x',valid,{getItem:()=>{throw Error('blocked')}})).toBeNull()
 expect(()=>writeSnapshot('x','data',{setItem:()=>{throw Error('full')}})).not.toThrow()
})
