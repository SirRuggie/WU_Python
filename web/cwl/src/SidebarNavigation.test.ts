import {expect,it} from 'vitest'
import {navigationSection,navigationLabel,visibleNavigationSections} from './SidebarNavigation'
it('keeps all personal pages together without staff grants',()=>{
 const sections=visibleNavigationSections(false,false)
 expect(sections.map(section=>section.label)).toEqual(['Home','Activity','My CWL'])
 expect(sections.flatMap(section=>section.items.map(item=>item.view))).toEqual(['home','search','todo','wars','events','signup','assignments'])
})
it('keeps CWL work separate from server configuration',()=>{
 const sections=visibleNavigationSections(true,false,['cwl'])
 expect(sections.map(section=>section.label)).toEqual(['Home','Activity','My CWL','Staff','CWL'])
 expect(sections.find(section=>section.id==='cwl-management')?.items.map(item=>item.view)).toContain('roster')
 expect(navigationSection('cwl-returns')).toBe('CWL')
})
it('preserves every explicit scope without exposing other tools',()=>{
 for(const [scope,view] of Object.entries({clans:'clan-management',clan_weights:'weight-trial',strikes:'strikes',strikes_add:'strikes',strikes_remove:'strikes',member_roles:'members-settings',recruitment:'applications-settings',tickets:'applications-settings',fwa:'fwa-settings',text_commands:'text-commands',server_tools:'connections-settings'})){
  const staff=visibleNavigationSections(false,false,[scope]).filter(section=>!['my-dashboard','activity','my-cwl','staff-overview'].includes(section.id))
  expect(staff.flatMap(section=>section.items.map(item=>item.view))).toEqual(scope==='tickets'?['tickets',view]:scope==='text_commands'?[view,'image-gallery']:scope.startsWith('strikes')?[view,'replacements']:scope==='member_roles'?['members-settings','moderation']:[view])
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

it('renders one combined Roster entry in the staff sidebar only', async () => {
 const {renderToStaticMarkup} = await import('react-dom/server')
 const {createElement} = await import('react')
 const {default: SidebarNavigation} = await import('./SidebarNavigation')
 const props = {userId:'audit',view:'roster' as const,canEdit:true,isOwner:true,onNavigate:()=>{}}
 expect(renderToStaticMarkup(createElement(SidebarNavigation,props))).toContain('Roster')
 expect(renderToStaticMarkup(createElement(SidebarNavigation,{...props,canEdit:false,isOwner:false}))).not.toContain('Roster')
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
 expect(views(['clans'])).not.toContain('roster')
})

it('keeps issue history owner-only even for CWL staff',()=>{
 expect(visibleNavigationSections(true,false,['cwl_signups']).flatMap(s=>s.items).some(i=>i.view==='issues')).toBe(false)
})

it('offers the same roster destination to signup and placement staff without exposing publishing', () => {
 for (const permissions of [['cwl_signups'], ['cwl_roster'], ['cwl_signups', 'cwl_roster']]) {
  const views = visibleNavigationSections(true, false, permissions).flatMap(section => section.items.map(item => item.view))
  expect(views.filter(view => view === 'roster')).toHaveLength(1)
  expect(views).not.toContain('manage-signups')
  expect(views).not.toContain('publication')
 }
})

it('does not render empty nested CWL groups for roster-only or signup-only staff', async () => {
 const {renderToStaticMarkup} = await import('react-dom/server')
 const React = await import('react')
 const {default: Sidebar} = await import('./SidebarNavigation')
 const render = (permissions: string[]) => renderToStaticMarkup(React.createElement(Sidebar, {
  userId: 'audit', view: 'roster', canEdit: true, isOwner: false, permissions, onNavigate: () => {},
 }))

 for (const permissions of [['cwl_roster'], ['cwl_signups']]) {
  const markup = render(permissions)
  expect(markup).toContain('Roster')
  expect(markup).not.toContain('Reminders')
  expect(markup).not.toContain('Results &amp; bonuses')
 }
})

it('renders publish-only access and results exports in their CWL sidebar groups', async () => {
 const {renderToStaticMarkup} = await import('react-dom/server')
 const React = await import('react')
 const {default: Sidebar} = await import('./SidebarNavigation')
 const render = (permissions: string[]) => renderToStaticMarkup(React.createElement(Sidebar, {
  userId: 'audit', view: 'publication', canEdit: true, isOwner: false, permissions, onNavigate: () => {},
 }))

 const publishOnly = render(['cwl_publish'])
 expect(publishOnly).toContain('Publish roster')
 expect(publishOnly).not.toContain('Roster</span>')
 expect(publishOnly).not.toContain('Exports &amp; history')

 const results = render(['cwl_results'])
 expect(results).toContain('Exports &amp; history')
 expect(results).toContain('Results &amp; bonuses')
 expect(results).not.toContain('Publish roster')
})

it('names staff destinations without granting access',()=>{
 expect(navigationLabel('publication')).toBe('Publish roster')
 expect(navigationLabel('connections-settings')).toBe('Integrations')
 expect(visibleNavigationSections(false,false).flatMap(section=>section.items).some(item=>item.view==='publication')).toBe(false)
})

it('puts member destinations first and collapses permission-filtered staff tools', async () => {
 const {renderToStaticMarkup} = await import('react-dom/server')
 const React = await import('react')
 const {default: Sidebar} = await import('./SidebarNavigation')
 const render = (view: 'home' | 'roster', permissions: string[]) => renderToStaticMarkup(React.createElement(Sidebar, {
  userId: 'audit', view, canEdit: permissions.length > 0, isOwner: false, permissions, onNavigate: () => {},
 }))
 const member = render('home', ['cwl_roster'])
 expect(member.indexOf('My clan assignments')).toBeLessThan(member.indexOf('Staff tools'))
 expect(member).toContain('aria-expanded="false" aria-controls="navigation-staff-tools"')
 expect(member).toContain('id="navigation-staff-tools" class="navigation-children navigation-staff-children" hidden=""')
 expect(member.indexOf('Staff tools')).toBeLessThan(member.indexOf('Staff overview'))
 const staff = render('roster', ['cwl_roster'])
 expect(staff).toContain('aria-expanded="true" aria-controls="navigation-staff-tools"')
 expect(staff).toContain('aria-current="page"')
 expect(staff).toContain('Roster')
 expect(render('home', [])).not.toContain('Staff tools')
})


it('shows Moderation only to staff with member-role access', () => {
 const {items} = visibleNavigationSections(true, false, ['member_roles']).find(section => section.id === 'server-tools')!
 expect(items.some(item => item.view === 'moderation' && item.label === 'Moderation')).toBe(true)
 expect(visibleNavigationSections(true, false, ['server_tools']).flatMap(section => section.items).some(item => item.view === 'moderation')).toBe(false)
 expect(visibleNavigationSections(true, false, ['member_roles']).flatMap(section => section.items).some(item => item.view === 'member-activity')).toBe(false)
})
