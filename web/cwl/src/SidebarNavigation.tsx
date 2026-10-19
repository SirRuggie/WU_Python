import { useEffect, useState } from 'react'

export type DashboardView = 'declaration' | 'image-gallery' | 'tickets' | 'staff-overview' | 'clan-management' | 'members-settings' | 'applications-settings' | 'fwa-settings' | 'connections-settings' | 'cwl-returns' | 'text-commands' | 'manage' | 'reminders' | 'todo' | 'home' | 'exports' | 'signup' | 'assignments' | 'roster' | 'publication' | 'participation' | 'bonuses' | 'staff' | 'access'
type Item = { view: DashboardView; label: string; icon: string; access?: 'owner'; permissions?: string[] }
type Section = { id: string; label: string; icon: string; items: Item[]; access?: 'staff' | 'owner' }
// Add future working features here; permission checks still live on the server.
const sections: Section[] = [
  { id: 'my-dashboard', label: 'My dashboard', icon: '🏠', items: [
    { view: 'staff-overview', label: 'Staff overview', icon: '▤', permissions: ['cwl','clans','text_commands','recruitment','tickets','member_roles','fwa','server_tools'] },
    { view: 'home', label: 'Home', icon: '⌂' },
    { view: 'todo', label: 'To do', icon: '✅' },
    { view: 'signup', label: 'CWL signups', icon: '◈' },
    { view: 'assignments', label: 'My clan assignments', icon: '✦' },
  ] },
  { id: 'cwl-management', label: 'CWL', icon: '🏆', access: 'staff', items: [
    { view: 'roster', label: 'Roster', icon: '📋' },
    { view: 'declaration', label: 'Declaration readiness check', icon: '✅' },
    { view: 'cwl-returns', label: 'Return reminders', icon: '↩' },
    { view: 'reminders', label: 'Signup reminders', icon: '✉' },
    { view: 'publication', label: 'Publish roster', icon: '▣' },
    { view: 'participation', label: 'Results & participation', icon: '✧' },
    { view: 'bonuses', label: 'Bonus medals', icon: '✧' },
    { view: 'exports', label: 'Export season', icon: '↓' },
    { view: 'staff', label: 'CWL settings', icon: '▦' },
  ] },
  { id: 'clans', label: 'Clan management', icon: '🛡', items: [
    {view:'clan-management',label:'Family clans',icon:'◈',permissions:['clans']},
  ] },
  { id: 'tickets', label: 'Tickets', icon: '✉', items: [
    { view: 'tickets', label: 'Browse tickets', icon: '▤', permissions: ['tickets'] },
  ] },
  { id: 'server-tools', label: 'Server tools', icon: '🛠', items: [
    { view: 'members-settings', label: 'Members & roles', icon: '♙', permissions: ['member_roles'] },
    { view: 'applications-settings', label: 'Applications & tickets', icon: '✉', permissions: ['recruitment','tickets'] },
    { view: 'fwa-settings', label: 'FWA tools', icon: '⚔', permissions: ['fwa'] },
    { view: 'text-commands', label: 'Command triggers', icon: '!', permissions: ['text_commands'] },
  ] },
  { id: 'settings', label: 'Settings', icon: '⚙', items: [
    { view: 'image-gallery', label: 'Image Gallery', icon: '▧', permissions: ['text_commands'] },
    { view: 'connections-settings', label: 'Integrations', icon: '⚙', permissions: ['server_tools'] },
    { view: 'access', label: 'Staff access', icon: '♙', access: 'owner' },
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
  const itemButton = (item: Item) => <button key={item.view} aria-current={itemActive(item) ? 'page' : undefined} onClick={() => onNavigate(item.view)}><span className="navigation-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span></button>
  return <nav aria-label="Warriors United navigation">
    {visibleNavigationSections(canEdit, isOwner, permissions).map(section => {
      const active = section.items.some(item => item.view === view)
      return <section className={`navigation-section${active ? ' contains-current' : ''}`} key={section.id}>
        <button className="navigation-toggle" aria-expanded={!!expanded[section.id]} aria-controls={`navigation-${section.id}`} onClick={() => setExpanded(current => ({ ...current, [section.id]: !current[section.id] }))}>
          <span className="navigation-icon" aria-hidden="true">{section.icon}</span><span>{section.label}</span><span className="navigation-chevron" aria-hidden="true">{expanded[section.id] ? '⌄' : '›'}</span>
        </button>
        <div id={`navigation-${section.id}`} className="navigation-children" hidden={!expanded[section.id]}>{section.id === 'cwl-management' ? <>
          {section.items.filter(item => item.view === 'roster' || item.view === 'declaration').map(itemButton)}
          {[{id:'cwl-reminders',label:'🔔 Reminders',views:['reminders','cwl-returns']},{id:'cwl-results',label:'🏅 Results & bonuses',views:['participation','bonuses']}].map(group => <div key={group.id}><button className="navigation-toggle" aria-expanded={!!expanded[group.id]} aria-controls={group.id} onClick={() => setExpanded(current => ({...current,[group.id]:!current[group.id]}))}>{group.label}<span className="navigation-chevron" aria-hidden="true">{expanded[group.id] ? '⌄' : '›'}</span></button><div id={group.id} className="navigation-children" hidden={!expanded[group.id]}>{section.items.filter(item => group.views.includes(item.view)).map(itemButton)}</div></div>)}
          {section.items.filter(item => item.view === 'staff').map(itemButton)}
        </> : section.items.map(itemButton)}</div>
      </section>
    })}
  </nav>
}
