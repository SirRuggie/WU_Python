import DashboardIcon, { type DashboardIconName } from './DashboardIcon'
import { useEffect, useState } from 'react'

export const dashboardViews = ['search', 'wars', 'events', 'declaration', 'image-gallery', 'tickets', 'staff-overview', 'clan-management', 'strikes', 'replacements', 'members-settings', 'applications-settings', 'fwa-settings', 'connections-settings', 'cwl-returns', 'text-commands', 'manage', 'reminders', 'todo', 'home', 'exports', 'signup', 'assignments', 'roster', 'publication', 'participation', 'bonuses', 'staff', 'access'] as const
export type DashboardView = typeof dashboardViews[number]
type Item = { view: DashboardView; label: string; icon: DashboardIconName; access?: 'owner'; permissions?: string[] }
type Section = { id: string; label: string; icon: DashboardIconName; items: Item[]; access?: 'staff' | 'owner' }
// Add future working features here; permission checks still live on the server.
const sections: Section[] = [
  { id: 'my-dashboard', label: 'Home', icon: 'home', items: [
    { view: 'home', label: 'Home', icon: 'home' },
    { view: 'search', label: 'Search', icon: 'search' },
  ] },
  { id: 'activity', label: 'Activity', icon: 'tasks', items: [
    { view: 'todo', label: 'Tasks', icon: 'tasks' },
    { view: 'wars', label: 'Wars', icon: 'war' },
    { view: 'events', label: 'Events', icon: 'calendar' },
  ] },
  { id: 'my-cwl', label: 'My CWL', icon: 'trophy', items: [
    { view: 'signup', label: 'CWL signups', icon: 'signup' },
    { view: 'assignments', label: 'My clan assignments', icon: 'shield' },
  ] },
  { id: 'staff-overview', label: 'Staff', icon: 'overview', items: [
    { view: 'staff-overview', label: 'Staff overview', icon: 'overview', permissions: ['cwl','clans','text_commands','recruitment','tickets','member_roles','fwa','server_tools'] },
  ] },
  { id: 'cwl-management', label: 'CWL', icon: 'trophy', access: 'staff', items: [
    { view: 'roster', label: 'Roster', icon: 'roster' },
    { view: 'declaration', label: 'Declaration readiness check', icon: 'tasks' },
    { view: 'cwl-returns', label: 'Return reminders', icon: 'return' },
    { view: 'reminders', label: 'Signup reminders', icon: 'mail' },
    { view: 'publication', label: 'Publish roster', icon: 'publish' },
    { view: 'participation', label: 'Results & participation', icon: 'results' },
    { view: 'bonuses', label: 'Bonus medals', icon: 'medal' },
    { view: 'exports', label: 'Export season', icon: 'download' },
    { view: 'staff', label: 'CWL settings', icon: 'settings' },
  ] },
  { id: 'clans', label: 'Clan management', icon: 'shield', items: [
    {view:'clan-management',label:'Family clans',icon:'shield',permissions:['clans']},
    {view:'strikes',label:'Strikes',icon:'flag',permissions:['strikes','strikes_add','strikes_remove']},
    {view:'replacements',label:'Replacements',icon:'replace',permissions:['strikes','strikes_add','strikes_remove']},
  ] },
  { id: 'tickets', label: 'Tickets', icon: 'mail', items: [
    { view: 'tickets', label: 'Browse tickets', icon: 'ticket', permissions: ['tickets'] },
  ] },
  { id: 'server-tools', label: 'Server tools', icon: 'tools', items: [
    { view: 'members-settings', label: 'Members & roles', icon: 'users', permissions: ['member_roles'] },
    { view: 'applications-settings', label: 'Applications & tickets', icon: 'mail', permissions: ['recruitment','tickets'] },
    { view: 'fwa-settings', label: 'FWA tools', icon: 'war', permissions: ['fwa'] },
    { view: 'text-commands', label: 'Command triggers', icon: 'command', permissions: ['text_commands'] },
  ] },
  { id: 'settings', label: 'Settings', icon: 'settings', items: [
    { view: 'image-gallery', label: 'Image Gallery', icon: 'image', permissions: ['text_commands'] },
    { view: 'connections-settings', label: 'Integrations', icon: 'connect', permissions: ['server_tools'] },
    { view: 'access', label: 'Staff access', icon: 'users', access: 'owner' },
  ] },
]
// Navigation mirrors explicit grants; every API still checks authorization.
export function visibleNavigationSections(canEdit: boolean, isOwner: boolean, permissions: string[] = []) {
  return sections.filter(section => !section.access || (section.access === 'staff' ? canEdit : isOwner))
    .map(section => ({ ...section, items: section.items.filter(item =>
      (item.access !== 'owner' || isOwner) && (isOwner || !item.permissions || item.permissions.some(scope => permissions.includes(scope)))) }))
    .filter(section => section.items.length > 0)
}
export function navigationSection(view: DashboardView) {
  return sections.find(section => section.items.some(item => item.view === view))?.label
}
export default function SidebarNavigation({ userId, view, canEdit, isOwner, permissions = [], onNavigate }: {
  userId: string; view: DashboardView; canEdit: boolean; isOwner: boolean; permissions?: string[]; onNavigate: (view: DashboardView) => void
}) {
  const key = `wu-navigation-v2:${userId}`
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || '{}')
      return Object.fromEntries(sections.map(section => [section.id, typeof saved?.[section.id] === 'boolean' ? saved[section.id] : section.id === 'my-dashboard']))
    } catch { return { 'my-dashboard': true } }
  })
  useEffect(() => {
    const active = sections.find(section => section.items.some(item => item.view === view))
    const group = ['reminders','cwl-returns'].includes(view) ? 'cwl-reminders' : ['participation','bonuses','exports'].includes(view) ? 'cwl-results' : null
    if (group) setExpanded(current => ({...current,[group]:true}))
    if (active) setExpanded(current => ({ ...current, [active.id]: true }))
  }, [view])
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(expanded)) } catch { /* Preferences are optional. */ } }, [expanded, key])
  const itemActive = (item: Item) => view === item.view || (item.view === 'roster' && view === 'publication')
  const itemButton = (item: Item) => <button key={item.view} aria-current={itemActive(item) ? 'page' : undefined} onClick={() => onNavigate(item.view)}><span className="navigation-icon" aria-hidden="true"><DashboardIcon name={item.icon} /></span><span>{item.label}</span></button>
  return <nav aria-label="Warriors United navigation">
    {visibleNavigationSections(canEdit, isOwner, permissions).map(section => {
      if (['my-dashboard', 'activity', 'my-cwl', 'staff-overview'].includes(section.id)) {
        return <section className="navigation-section navigation-everyday" key={section.id}>
          {section.id !== 'my-dashboard' && <h2 className="navigation-label">{section.label}</h2>}
          {section.items.map(itemButton)}
        </section>
      }
      const active = section.items.some(item => item.view === view)
      return <section className={`navigation-section${active ? ' contains-current' : ''}`} key={section.id}>
        <button className="navigation-toggle" aria-expanded={!!expanded[section.id]} aria-controls={`navigation-${section.id}`} onClick={() => setExpanded(current => ({ ...current, [section.id]: !current[section.id] }))}>
          <span className="navigation-icon" aria-hidden="true"><DashboardIcon name={section.icon} /></span><span>{section.label}</span><span className="navigation-chevron" aria-hidden="true"><DashboardIcon name={expanded[section.id] ? "chevronDown" : "chevronRight"} /></span>
        </button>
        <div id={`navigation-${section.id}`} className="navigation-children" hidden={!expanded[section.id]}>{section.id === 'cwl-management' ? <>
          {section.items.filter(item => item.view === 'roster' || item.view === 'declaration').map(itemButton)}
          {[{id:'cwl-reminders',label:'Reminders',icon:'bell' as const,views:['reminders','cwl-returns']},{id:'cwl-results',label:'Results & bonuses',icon:'medal' as const,views:['participation','bonuses']}].map(group => <div key={group.id}><button className="navigation-toggle" aria-expanded={!!expanded[group.id]} aria-controls={group.id} onClick={() => setExpanded(current => ({...current,[group.id]:!current[group.id]}))}><span className="navigation-icon"><DashboardIcon name={group.icon}/></span><span>{group.label}</span><span className="navigation-chevron" aria-hidden="true"><DashboardIcon name={expanded[group.id] ? "chevronDown" : "chevronRight"} /></span></button><div id={group.id} className="navigation-children" hidden={!expanded[group.id]}>{section.items.filter(item => group.views.includes(item.view)).map(itemButton)}</div></div>)}
          {section.items.filter(item => item.view === 'staff').map(itemButton)}
        </> : section.id === 'clans' ? <>
          {section.items.filter(item => item.view === 'clan-management').map(itemButton)}
          {section.items.some(item => item.view === 'strikes') && <div className="strikes-nav-group">
            {section.items.filter(item => item.view === 'strikes').map(itemButton)}
            <div className="navigation-children strikes-subnav">{section.items.filter(item => item.view === 'replacements').map(itemButton)}</div>
          </div>}
        </> : section.items.map(itemButton)}</div>
      </section>
    })}
  </nav>
}
