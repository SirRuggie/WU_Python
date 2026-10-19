import {expect,it} from 'vitest'
import {hasRoleActions} from './CommandBuilder'
it('hides role history for text, mentions, and reply buttons',()=>{
 expect(hasRoleActions([{type:'text',text:'Hello <@&123>'},{type:'actions',buttons:[{label:'Reply',action:{kind:'reply',command:'!hi'}}]}])).toBe(false)
})
it('finds role controls in nested cards and dropdowns',()=>{
 expect(hasRoleActions([{type:'container',color:'#ffffff',blocks:[{type:'select',placeholder:'Role',options:[{label:'Remove',action:{kind:'remove_role',role_id:'123'}}]}]}])).toBe(true)
 expect(hasRoleActions([{type:'actions',buttons:[{label:'Join',action:{kind:'add_role',role_id:'123'}}]}])).toBe(true)
})
