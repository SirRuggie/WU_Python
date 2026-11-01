import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {isValidElement,type ReactNode} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {actionConfirmation,type ManagementField} from './serverManagement'
const hook=vi.hoisted(()=>({index:0,refIndex:0,values:[] as unknown[],refs:[] as {current:unknown}[],effects:[] as (()=>void|(()=>void))[]}))
const transport=vi.hoisted(()=>vi.fn())
vi.mock('react',async importOriginal=>({...await importOriginal<typeof import('react')>(),
 useState:(initial:unknown)=>{const i=hook.index++;if(!(i in hook.values))hook.values[i]=typeof initial==='function'?(initial as ()=>unknown)():initial;return [hook.values[i],(next:unknown)=>{hook.values[i]=typeof next==='function'?(next as (old:unknown)=>unknown)(hook.values[i]):next}]},
 useRef:(initial:unknown)=>{const i=hook.refIndex++;return hook.refs[i]??(hook.refs[i]={current:initial})},
 useEffect:(effect:()=>void|(()=>void))=>{hook.effects.push(effect)},
}))
vi.mock('./api',()=>({api:transport}))
import MemberPicker,{type MemberOption} from './MemberPicker'
const ada:MemberOption={value:'111111111111111111',id:'111111111111111111',label:'Ada (@ada)',display_name:'Ada',username:'ada',role_ids:['999']}
const bob:MemberOption={...ada,value:'222222222222222222',id:'222222222222222222',label:'Bob (@bob)',display_name:'Bob',username:'bob',role_ids:[]}
function draw(value:string|string[]='',onChange=vi.fn(),compactSelection=false){
 hook.index=0;hook.refIndex=0;hook.effects=[]
 return {tree:MemberPicker({label:'Member',value,onChange,disabled:false,roles:[{value:'999',label:'Leader'}],compactSelection}),onChange}
}
function elements(node:ReactNode):{type:unknown;props:Record<string,unknown>}[]{
 if(Array.isArray(node))return node.flatMap(elements)
 if(!isValidElement<Record<string,unknown>>(node))return []
 return [{type:node.type,props:node.props},...elements(node.props.children as ReactNode)]
}
beforeEach(()=>{vi.useFakeTimers();hook.index=0;hook.refIndex=0;hook.values=[];hook.refs=[];hook.effects=[];transport.mockReset();vi.stubGlobal('window',{setTimeout,clearTimeout})})
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals()})
it('browses members immediately without assigning or preselecting anyone',async()=>{
 transport.mockResolvedValue({options:[ada,bob],next:null,truncated:false})
 const {onChange}=draw();const cleanup=hook.effects[0]()
 await vi.advanceTimersByTimeAsync(0)
 expect(transport).toHaveBeenCalledWith('/manage/members')
 expect(hook.values[1]).toEqual([ada,bob]);expect(onChange).not.toHaveBeenCalled()
 const {tree}=draw('',onChange)
 expect(elements(tree).filter(node=>node.type==='input'&&node.props.type==='radio').every(node=>node.props.checked===false)).toBe(true)
 if(cleanup)cleanup()
})
it('debounces searches and ignores an older request error after a new query',async()=>{
 let rejectOld!:(reason:unknown)=>void
 transport.mockReturnValueOnce(new Promise((_,reject)=>{rejectOld=reject})).mockResolvedValueOnce({options:[bob],next:null,truncated:false})
 hook.values[0]='Ada';draw();const cleanupOld=hook.effects[0]()
 await vi.advanceTimersByTimeAsync(299);expect(transport).not.toHaveBeenCalled()
 await vi.advanceTimersByTimeAsync(1);expect(transport).toHaveBeenCalledWith('/manage/members?q=Ada')
 if(cleanupOld)cleanupOld()
 hook.values[0]='Bob';draw();const cleanupNew=hook.effects[0]()
 await vi.advanceTimersByTimeAsync(300)
 rejectOld(new Error('Old request failed'));await Promise.resolve();await Promise.resolve()
 expect(hook.values[1]).toEqual([bob]);expect(hook.values[5]).toBe('');expect(hook.values[4]).toBe(false)
 if(cleanupNew)cleanupNew()
})
it('loading another page keeps selected members and deduplicates overlapping results',async()=>{
 hook.values=['',[ada],[ada],'page2',false,'',false,0]
 transport.mockResolvedValue({options:[ada,bob],next:null,truncated:false})
 const {tree,onChange}=draw(ada.value)
 const button=elements(tree).find(node=>node.type==='button'&&node.props.children==='Show more')!
 ;(button.props.onClick as ()=>void)();await Promise.resolve();await Promise.resolve();await Promise.resolve()
 expect(transport).toHaveBeenCalledWith('/manage/members?after=page2')
 expect(hook.values[1]).toEqual([ada,bob]);expect(hook.values[2]).toEqual([ada,bob]);expect(onChange).not.toHaveBeenCalled()
 const next=draw(ada.value,onChange)
 const inputs=elements(next.tree).filter(node=>node.type==='input'&&node.props.type==='radio')
 expect(inputs.map(input=>input.props.checked)).toEqual([true,false])
})
it('displays lookup failures with a retry control instead of an empty success state',async()=>{
 transport.mockRejectedValue(new Error('Discord member access is unavailable'))
 draw();const cleanup=hook.effects[0]();await vi.advanceTimersByTimeAsync(0)
 const {tree}=draw();const html=renderToStaticMarkup(tree)
 expect(html).toContain('role="alert"');expect(html).toContain('Discord member access is unavailable');expect(html).toContain('Try again');expect(html).not.toContain('No members found.')
 if(cleanup)cleanup()
})
it('loads an existing selected member by ID without assigning roles',async()=>{
 transport.mockResolvedValue({options:[ada],next:null,truncated:false})
 const {onChange}=draw(ada.value);const cleanup=hook.effects[1]()
 await Promise.resolve();await Promise.resolve();await Promise.resolve()
 expect(transport).toHaveBeenCalledWith('/manage/members?id='+ada.value)
 expect(hook.values[2]).toEqual([ada]);expect(onChange).not.toHaveBeenCalled()
 if(cleanup)cleanup()
})
it('confirms member and role names instead of raw IDs',()=>{
 const fields:ManagementField[]=[{key:'member_id',label:'Member',type:'member',value:'',options:[ada]},{key:'role_ids',label:'Roles',type:'multiselect',value:[],options:[{value:'999',label:'Leader'}]}]
 const text=actionConfirmation('Add roles?',fields,{member_id:ada.value,role_ids:['999']})
 expect(text).toBe('Add roles?\n\nMember: Ada (@ada)\nRoles: Leader');expect(text).not.toContain(ada.value)
})
it('selecting a member only edits the draft and does not call a role endpoint',()=>{
 hook.values=['',[ada],[ada],null,false,'',false,0]
 const {tree,onChange}=draw()
 const radio=elements(tree).find(node=>node.type==='input'&&node.props.type==='radio')!
 ;(radio.props.onChange as (event:{target:{checked:boolean}})=>void)({target:{checked:true}})
 expect(onChange).toHaveBeenCalledWith(ada.value);expect(transport).not.toHaveBeenCalled()
})
it('shows selected member current role names in the profile summary',()=>{
 hook.values=['',[ada],[ada],null,false,'',false,0]
 const html=renderToStaticMarkup(draw(ada.value).tree)
 expect(html).toContain('Selected member');expect(html).toContain('Current roles: Leader');expect(html).not.toContain('Current roles: 999')
})

it('compact selection identifies the member and opens search only on request',()=>{
 hook.values=['',[ada],[ada],null,false,'',false,0,false]
 const {tree,onChange}=draw(ada.value,vi.fn(),true)
 const html=renderToStaticMarkup(tree)
 expect(html).not.toContain('Discord ID:');expect(html).not.toContain(ada.value)
 const change=elements(tree).find(node=>node.type==='button'&&node.props.children==='Change member')!
 expect(change).toBeDefined()
 ;(change.props.onClick as ()=>void)()
 expect(hook.values[8]).toBe(true)
 expect(onChange).not.toHaveBeenCalled();expect(transport).not.toHaveBeenCalled()
})
