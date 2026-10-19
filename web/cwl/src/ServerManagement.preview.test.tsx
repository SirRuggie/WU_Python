import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import type {ManagementDocument} from './serverManagement'
const hooks=vi.hoisted(()=>({index:0,values:[] as unknown[],setters:[] as ReturnType<typeof vi.fn>[],effects:[] as (()=>void|(()=>void))[]}))
const transport=vi.hoisted(()=>vi.fn())
vi.mock('react',async importOriginal=>{
 const actual=await importOriginal<typeof import('react')>()
 return {...actual,useState:(initial:unknown)=>{const index=hooks.index++;const value=index<hooks.values.length?hooks.values[index]:typeof initial==='function'?(initial as ()=>unknown)():initial;const setter=vi.fn();hooks.setters[index]=setter;return [value,setter]},useEffect:(effect:()=>void|(()=>void))=>{hooks.effects.push(effect)}}
})
vi.mock('./api',async importOriginal=>({...await importOriginal<typeof import('./api')>(),api:transport}))
import ServerManagement from './ServerManagement'
const document:ManagementDocument={id:'recruit',label:'Recruitment',description:'Message',group:'Messages',endpoint:'/manage/content/recruit',revision:'reviewed',preview_supported:true,fields:[{key:'message',label:'Message',type:'textarea',value:'Saved text'}],preview:[{type:'text',text:'Saved text'}]}
function renderDraft(){
 hooks.values=[[],'','',[],document,document,{message:'My unsaved text'},false,'','',document.preview,false,0,'',0,null,'','','edit']
 renderToStaticMarkup(<ServerManagement/>)
 return hooks.effects[3]
}
beforeEach(()=>{vi.useFakeTimers();hooks.index=0;hooks.values=[];hooks.effects=[];hooks.setters=[];transport.mockReset();vi.stubGlobal('window',{setTimeout,clearTimeout})})
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals()})
it('draft preview debounces, sends only edits, and never replaces the saved draft',async()=>{
 transport.mockResolvedValue({preview:[{type:'text',text:'Rendered draft'}]})
 const effect=renderDraft();const cleanup=effect()
 await vi.advanceTimersByTimeAsync(699);expect(transport).not.toHaveBeenCalled()
 await vi.advanceTimersByTimeAsync(1)
 expect(transport).toHaveBeenCalledWith('/manage/content/recruit/preview','POST',{revision:'reviewed',values:{message:'My unsaved text'}})
 expect(hooks.setters[10]).toHaveBeenCalledWith([{type:'text',text:'Rendered draft'}])
 expect(hooks.setters[6]).not.toHaveBeenCalled()
 expect(hooks.setters[5]).not.toHaveBeenCalled()
 if(cleanup)cleanup()
})
it('a late preview response cannot replace the next draft preview',async()=>{
 let resolve!:(value:unknown)=>void
 transport.mockReturnValue(new Promise(done=>{resolve=done}))
 const cleanup=renderDraft()()
 await vi.advanceTimersByTimeAsync(700)
 if(cleanup)cleanup()
 resolve({preview:[{type:'text',text:'Outdated text'}]});await Promise.resolve();await Promise.resolve()
 expect(hooks.setters[10]).not.toHaveBeenCalled()
 expect(hooks.setters[6]).not.toHaveBeenCalled()
})
it('preview errors preserve draft text and the previous valid preview',async()=>{
 transport.mockRejectedValue(new Error('Image cannot be loaded'))
 const cleanup=renderDraft()()
 await vi.advanceTimersByTimeAsync(700)
 expect(hooks.setters[17]).toHaveBeenCalledWith('Showing the last valid preview. Image cannot be loaded')
 expect(hooks.setters[10]).not.toHaveBeenCalled()
 expect(hooks.setters[6]).not.toHaveBeenCalled()
 if(cleanup)cleanup()
})
it('leaving before debounce prevents an obsolete preview request entirely',async()=>{
 const cleanup=renderDraft()();if(cleanup)cleanup()
 await vi.advanceTimersByTimeAsync(1000)
 expect(transport).not.toHaveBeenCalled()
})
it('saved preview is available before any edits',()=>{
 hooks.values=[[],'','',[],document,document,{message:'Saved text'},false,'','',null,false,0,'',0,null,'','','edit']
 renderToStaticMarkup(<ServerManagement/>)
 hooks.effects[3]()
 expect(hooks.setters[10]).toHaveBeenCalledWith(document.preview)
 expect(transport).not.toHaveBeenCalled()
})
it('reset tools are inside a closed More options disclosure',()=>{
 const withActions={...document,actions:[{id:'reset',label:'Reset to default',advanced:true}]}
 hooks.values=[[],'','',[],withActions,withActions,{message:'Saved text'},false,'','',document.preview,false,0,'',0,null,'','','edit']
 const html=renderToStaticMarkup(<ServerManagement/>)
 expect(html).toMatch(/<details class="manage-more-options"><summary>More options<\/summary>/)
 expect(html).toContain('Reset to default')
})
