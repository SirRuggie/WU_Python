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
 expect(sections.find(section=>section.id==='cwl-management')?.items.map(item=>item.view)).toContain('manage-signups')
 expect(navigationSection('cwl-returns')).toBe('CWL')
})
it('preserves every explicit scope without exposing other tools',()=>{
 for(const [scope,view] of Object.entries({clans:'clan-management',clan_weights:'weight-trial',strikes:'strikes',strikes_add:'strikes',strikes_remove:'strikes',member_roles:'members-settings',recruitment:'applications-settings',tickets:'applications-settings',fwa:'fwa-settings',text_commands:'text-commands',server_tools:'connections-settings'})){
  const staff=visibleNavigationSections(false,false,[scope]).filter(section=>!['my-dashboard','activity','my-cwl','staff-overview'].includes(section.id))
  expect(staff.flatMap(section=>section.items.map(item=>item.view))).toEqual(scope==='tickets'?['tickets',view]:scope==='text_commands'?[view,'image-gallery']:scope.startsWith('strikes')?[view,'replacements']:[view])
 }
})
it('shows owners all groups and every destination once',()=>{
 const sections=visibleNavigationSections(true,true)
 expect(sections.map(section=>section.label)).toEqual(['Home','Activity','My CWL','Staff','CWL','Clan management','Tickets','Server tools','Settings'])
 const views=sections.flatMap(section=>section.items.map(item=>item.view))
 expect(new Set(views).size).toBe(views.length)
 expect(views).toHaveLength(31)
 expect(sections.find(section=>section.id==='settings')?.items.map(item=>item.view)).toEqual(['image-gallery','connections-settings','issues','access'])
 expect(navigationSection('tickets')).toBe('Tickets')
 expect(navigationSection('applications-settings')).toBe('Server tools')
 expect(navigationSection('clan-management')).toBe('Clan management')
 expect(navigationSection('strikes')).toBe('Clan management')
 expect(navigationSection('replacements')).toBe('Clan management')
})

it('renders Manage signups in the staff sidebar only', async () => {
 const {renderToStaticMarkup} = await import('react-dom/server')
 const {createElement} = await import('react')
 const {default: SidebarNavigation} = await import('./SidebarNavigation')
 const props = {userId:'audit',view:'manage-signups' as const,canEdit:true,isOwner:true,onNavigate:()=>{}}
 expect(renderToStaticMarkup(createElement(SidebarNavigation,props))).toContain('Manage signups')
 expect(renderToStaticMarkup(createElement(SidebarNavigation,{...props,canEdit:false,isOwner:false}))).not.toContain('Manage signups')
})

it('renders the weight trial under clan management for clan staff only',async()=>{
 const {renderToStaticMarkup}=await import('react-dom/server')
 const React=await import('react')
 const {default:Sidebar}=await import('./SidebarNavigation')
 const render=(permissions:string[])=>renderToStaticMarkup(React.createElement(Sidebar,{userId:'1',view:'weight-trial',canEdit:false,isOwner:false,permissions,onNavigate:()=>{}}))
 expect(render(['clan_weights'])).toContain('Clan weights')
 expect(render(['clans'])).not.toContain('Clan weights')
 expect(render([])).not.toContain('Clan weights')
})

it('separates CWL action permissions from clan management and access settings',()=>{
 const views=(permissions:string[])=>visibleNavigationSections(true,false,permissions).flatMap(s=>s.items.map(i=>i.view))
 expect(views(['cwl_roster'])).toContain('roster')
 expect(views(['cwl_roster'])).not.toContain('publication')
 expect(views(['cwl_publish'])).toContain('publication')
 expect(views(['cwl_publish'])).not.toContain('roster')
 expect(views(['cwl_send'])).toContain('bonuses')
 expect(views(['cwl_send'])).not.toContain('access')
 expect(views(['clans'])).not.toContain('manage-signups')
})

it('keeps issue history owner-only even for CWL staff',()=>{
 expect(visibleNavigationSections(true,false,['cwl_signups']).flatMap(s=>s.items).some(i=>i.view==='issues')).toBe(false)
})
