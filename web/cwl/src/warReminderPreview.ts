/** Display Discord's timestamps locally without changing the outgoing payload. */
export function reminderPreviewText(text:string, now=Date.now()):string {
 return text.replace(/<t:(\d+):([Rt])>/g,(_,seconds:string,style:string)=>{
  const at=new Date(Number(seconds)*1000)
  if(style==='t')return at.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})
  const minutes=Math.max(0,Math.round((at.getTime()-now)/60000))
  if(minutes===0)return 'now'
  return minutes>=60&&minutes%60===0?`in ${minutes/60} hour${minutes===60?'':'s'}`:`in ${minutes} minute${minutes===1?'':'s'}`
 })
}
