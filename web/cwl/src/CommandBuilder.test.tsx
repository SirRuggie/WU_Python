import {expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import CommandBuilder,{commandBlocks,commandPreview,type Command} from './CommandBuilder'
const value:Command={command:'!cwl',enabled:true,text:'Above embed',title:'Heading',description:'Body',image_url:'https://example.com/img.png',color:'#e2b332'}
it('keeps legacy cards readable without losing their content',()=>{
 expect(commandBlocks(value).map(block=>block.type)).toEqual(['text','text','image'])
 expect(commandPreview(value)[0]).toEqual({type:'text',text:'Above embed'})
 expect(commandPreview(value)[1].children?.[0].text).toBe('## Heading')
})
it('previews V2 ordering, link buttons, and separator settings',()=>{
 const parts=commandPreview({...value,blocks:[{type:'separator',divider:false,spacing:2},{type:'buttons',buttons:[{label:'Sign up',url:'https://cwl.ruggie.zone/'}]}]})
 expect(parts[1].children?.[0]).toEqual({type:'separator',divider:false,spacing:2})
 expect(parts[1].children?.[1].children?.[0]).toMatchObject({type:'button',label:'Sign up',style:5})
})
it('labels blocks and exposes accessible reordering controls',()=>{
 const html=renderToStaticMarkup(<CommandBuilder value={value} onChange={()=>{}}/>)
 expect(html).toContain('Embed content');expect(html).toContain('+ Link buttons')
 expect(html).toContain('Move block 1 down');expect(html).toContain('aria-expanded="false"')
})
it('shows custom editor names without putting them in the message',()=>{
 const draft={...value,blocks:[{type:'text' as const,text:'Welcome',name:'Private label'}]}
 expect(renderToStaticMarkup(<CommandBuilder value={draft} onChange={()=>{}}/>)).toContain('Private label')
 expect(JSON.stringify(commandPreview(draft))).not.toContain('Private label')
})
it('previews galleries and sections with accessories',()=>{
 const parts=commandPreview({...value,blocks:[{type:'gallery',items:[{url:'https://example.com/a',description:'Badge'}]},{type:'section',texts:['Hello'],accessory:{type:'button',label:'Open',url:'https://example.com'}}]})
 expect(parts[1].children?.[0].items).toHaveLength(1)
 expect(parts[1].children?.[1].accessory).toMatchObject({type:'button',label:'Open'})
})
it('keeps independent cards separate and previews files and actions',()=>{
 const parts=commandPreview({...value,text:'',blocks:[{type:'container',color:'#123456',blocks:[{type:'text',text:'First'}]},{type:'container',color:'#abcdef',spoiler:true,blocks:[{type:'file',file_id:'a'.repeat(64),filename:'guide.txt',size:5},{type:'actions',buttons:[{label:'More',style:3,action:{kind:'reply',command:'!more'}}]},{type:'select',placeholder:'Pick one',options:[{label:'Help',action:{kind:'reply',command:'!help'}}]}]}]})
 expect(parts).toHaveLength(2);expect(parts[0].accent).toBe('#123456');expect(parts[1].accent).toBe('#abcdef');expect(parts[1].spoiler).toBe(true)
 expect(parts[1].children?.[0]).toMatchObject({type:'file',label:'guide.txt',size:5})
 expect(parts[1].children?.[1].children?.[0]).toMatchObject({type:'button',label:'More',style:3})
 expect(parts[1].children?.[2].options?.[0].label).toBe('Help')
})
