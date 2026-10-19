// Preserve Discord-only formatting without interpreting HTML or executable content.
type Node={type:string;value?:string;children?:Node[];data?:{hName?:string;hProperties?:Record<string,unknown>};position?:{start:{offset?:number}}}
export default function discordMarkdownPlugin(){return (tree:Node,file:{value?:unknown})=>{
 const source=String(file.value||'')
 function visit(node:Node){
  if(node.type==='code'||node.type==='inlineCode')return
  if(node.type==='strong'&&node.position?.start.offset!==undefined&&source.slice(node.position.start.offset,node.position.start.offset+2)==='__')node.data={hName:'u'}
  if(node.type==='paragraph'&&node.children?.[0]?.type==='text'&&node.children[0].value?.startsWith('-# ')){node.data={hName:'small',hProperties:{className:'discord-subtext'}};node.children[0].value=node.children[0].value.slice(3)}
  if(!node.children)return
  const next:Node[]=[]
  for(const child of node.children){
   if(child.type==='text'&&child.value?.includes('||')){
    let end=0;const expression=/\|\|([^\n]+?)\|\|/g
    for(const match of child.value.matchAll(expression)){const start=match.index!;if(start>end)next.push({type:'text',value:child.value.slice(end,start)});next.push({type:'emphasis',data:{hName:'span',hProperties:{className:'discord-spoiler-text'}},children:[{type:'text',value:match[1]}]});end=start+match[0].length}
    if(end){if(end<child.value.length)next.push({type:'text',value:child.value.slice(end)});continue}
   }
   visit(child);next.push(child)
  }
  node.children=next
 }
 visit(tree)
}}
