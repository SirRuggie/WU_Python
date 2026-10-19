import {expect,it} from 'vitest'
import {insertMention,namedMentions} from './MentionText'
it('inserts at the cursor and replaces selected text without changing surrounding text',()=>{
 expect(insertMention('Hello there!',6,11,'<@123>')).toBe('Hello <@123>!')
 expect(insertMention('ab',1,1,'<@&456>')).toBe('a <@&456> b')
})
it('previews known members and roles by name without changing stored tokens',()=>{
 const text='<@123> and <@&456>'
 expect(namedMentions(text,{'user:123':'Ruggie','role:456':'Staff'})).toBe('**@Ruggie** and **@Staff**')
 expect(namedMentions(text,{})).toBe(text)
})
