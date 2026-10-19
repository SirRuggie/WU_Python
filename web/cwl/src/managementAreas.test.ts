import {expect,it} from 'vitest'
import {areaSections,sectionArea} from './managementAreas'
import type {ManagementSection} from './serverManagement'
const item=(id:string,extra:Partial<ManagementSection>={}):ManagementSection=>({id,label:id,description:'',group:'Old group',allowed:true,...extra})
it('keeps application messages, channels and testing in clear groups',()=>{
 const rows=areaSections(['gauntlet--apply','publish--apply','question--main','staff--main','destination--welcome','ticket_settings','ticket_testing','fwa_bases','roles'].map(id=>item(id)),'applications-settings')
 expect(rows.map(row=>row.group)).toEqual(['Messages','Messages','Questions','Staff messages','Channels & access','Channels & access','Testing'])
})
it('does not show denied editors or unrelated settings',()=>{
 expect(areaSections([item('roles',{allowed:false}),item('band_monitor')],'members-settings')).toEqual([])
 expect(areaSections([item('cwl_rosters'),item('cwl-roster',{destination:'roster'})],'cwl-returns').map(row=>row.id)).toEqual(['cwl_rosters'])
})
it('maps war tools and connection controls separately',()=>{
 for(const id of ['fwa_bases','fwa_weight','fwa_points','fwa_sync','fwa_blacklist','war--win'])expect(sectionArea(item(id))).toBe('fwa-settings')
 expect(sectionArea(item('band_monitor'))).toBe('connections-settings')
 expect(sectionArea(item('roles'))).toBe('members-settings')
})
