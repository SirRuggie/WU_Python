import {expect,it} from 'vitest'
import {navigationSection,visibleNavigationSections} from './SidebarNavigation'
it('keeps all personal pages together without staff grants',()=>{
 const sections=visibleNavigationSections(false,false)
 expect(sections.map(section=>section.label)).toEqual(['Home','Activity','My CWL'])
 expect(sections.flatMap(section=>section.items.map(item=>item.view))).toEqual(['home','search','todo','wars','events','signup','assignments'])
})
it('keeps CWL work separate from server configuration',()=>{
 const sections=visibleNavigationSections(true,false,['cwl'])
 expect(sections.map(section=>section.label)).toEqual(['Home','Activity','My CWL','Staff','CWL'])
 expect(sections.find(section=>section.id==='cwl-management')?.items.map(item=>item.view)).toContain('cwl-returns')
 expect(navigationSection('cwl-returns')).toBe('CWL')
})
it('preserves every explicit scope without exposing other tools',()=>{
 for(const [scope,view] of Object.entries({clans:'clan-management',strikes:'strikes',strikes_add:'strikes',strikes_remove:'strikes',member_roles:'members-settings',recruitment:'applications-settings',tickets:'applications-settings',fwa:'fwa-settings',text_commands:'text-commands',server_tools:'connections-settings'})){
  const staff=visibleNavigationSections(false,false,[scope]).filter(section=>!['my-dashboard','activity','my-cwl','staff-overview'].includes(section.id))
  expect(staff.flatMap(section=>section.items.map(item=>item.view))).toEqual(scope==='tickets'?['tickets',view]:scope==='text_commands'?[view,'image-gallery']:scope.startsWith('strikes')?[view,'replacements']:[view])
 }
})
it('shows owners all groups and every destination once',()=>{
 const sections=visibleNavigationSections(true,true)
 expect(sections.map(section=>section.label)).toEqual(['Home','Activity','My CWL','Staff','CWL','Clan management','Tickets','Server tools','Settings'])
 const views=sections.flatMap(section=>section.items.map(item=>item.view))
 expect(new Set(views).size).toBe(views.length)
 expect(views).toHaveLength(28)
 expect(sections.find(section=>section.id==='settings')?.items.map(item=>item.view)).toEqual(['image-gallery','connections-settings','access'])
 expect(navigationSection('tickets')).toBe('Tickets')
 expect(navigationSection('applications-settings')).toBe('Server tools')
 expect(navigationSection('clan-management')).toBe('Clan management')
 expect(navigationSection('strikes')).toBe('Clan management')
 expect(navigationSection('replacements')).toBe('Clan management')
})
