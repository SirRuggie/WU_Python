import {expect,it} from 'vitest'
import {changedValues,fieldError,fieldValues,filterSections,type ManagementField} from './serverManagement'
const fields:ManagementField[]=[{key:'message',label:'Message',type:'textarea',value:'Original'},{key:'enabled',label:'Enabled',type:'boolean',value:false}]
it('only submits changed settings, preserving false and empty edits',()=>{expect(changedValues(fields,fieldValues(fields))).toEqual({});expect(changedValues(fields,{message:'',enabled:true})).toEqual({message:'',enabled:true})})
it('finds simple words across labels and descriptions without exposing denied pages',()=>{const sections=[{id:'a',label:'War messages',description:'Change reminder text',group:'War'},{id:'b',label:'War roles',description:'Choose roles',group:'War',allowed:false}];expect(filterSections(sections,'war text').map(s=>s.id)).toEqual(['a']);expect(filterSections(sections,'').map(s=>s.id)).toEqual(['a'])})
it('validates numeric limits without treating zero as blank',()=>{const field:ManagementField={key:'hours',label:'Hours',type:'number',value:0,min:0,max:24,required:true};expect(fieldError(field,0)).toBeNull();expect(fieldError(field,'')).toContain('required');expect(fieldError(field,25)).toContain('24');expect(fieldError(field,'abc')).toContain('number')})
import {ManagementRequestIds} from './serverManagement'
it('reuses uncertain operation IDs only for the same action revision and values',()=>{let number=0;const ids=new ManagementRequestIds(()=>`request-${++number}`);const first=ids.key('/roles/add',1,{member:'a',role:'b'});expect(ids.get(first)).toBe('request-1');expect(ids.get(ids.key('/roles/add',1,{role:'b',member:'a'}))).toBe('request-1');expect(ids.get(ids.key('/roles/remove',1,{member:'a',role:'b'}))).toBe('request-2');expect(ids.get(ids.key('/roles/add',2,{member:'a',role:'b'}))).toBe('request-3');ids.complete(first);expect(ids.get(first)).toBe('request-4')})
import {safeDiscordUrl} from './serverManagement'
it('links only to HTTPS Discord channels without allowing spoofed hosts',()=>{expect(safeDiscordUrl('https://discord.com/channels/123/456/789')).toBe('https://discord.com/channels/123/456/789');for(const url of ['javascript:alert(1)','https://discord.com.evil.test/channels/1/2','https://evil.test@discord.com/channels/1/2','http://discord.com/channels/1/2','https://discord.com/login'])expect(safeDiscordUrl(url)).toBeNull()})

import {actionConfirmation} from './serverManagement'
it('reviews selected clan names before a bulk action',()=>{const clans:ManagementField[]=[{key:'clans',label:'Choose clans',type:'multiselect',value:[],options:[{value:'FWA:#A',label:'Alpha · FWA'},{value:'MAIN:#B',label:'Beta · MAIN'}]}];expect(actionConfirmation('Send?',clans,{clans:['MAIN:#B','FWA:#A']})).toBe('Send?\n\n2 clans selected:\nBeta · MAIN\nAlpha · FWA');expect(actionConfirmation('Save?',fields,{})).toBe('Save?')})


import {actionNeedsConfirmation} from './serverManagement'
it('skips confirmation only for known read-only checks', () => {
 expect(actionNeedsConfirmation('band_monitor','status')).toBe(false)
 expect(actionNeedsConfirmation('fwa_sync','check_feed')).toBe(false)
 for (const [section, action] of [
  ['band_monitor','debug_on'], ['band_monitor','debug_off'],
  ['fwa_sync','test_dm'], ['fwa_points','enable'], ['fwa_points','disable'],
  ['unknown','status'], ['band_monitor','check_feed'], ['fwa_sync','status'],
 ]) expect(actionNeedsConfirmation(section,action)).toBe(true)
})
