import DashboardIcon, { type DashboardIconName } from './DashboardIcon'
import { useEffect, useRef, useState } from 'react'

export const dashboardViews = ['weight-trial', 'search', 'wars', 'events', 'declaration', 'image-gallery', 'tickets', 'staff-overview', 'clan-management', 'strikes', 'replacements', 'members-settings', 'member-activity', 'moderation', 'applications-settings', 'fwa-settings', 'connections-settings', 'cwl-returns', 'text-commands', 'manage', 'reminders', 'todo', 'home', 'exports', 'signup', 'assignments', 'roster', 'publication', 'participation', 'bonuses', 'staff', 'access', 'issues'] as const
export type DashboardView = typeof dashboardViews[number]
type Item = { signupPanel?: 'register' | 'saved'; step?: 'review' | 'announce'; view: DashboardView; label: string; icon: DashboardIconName; access?: 'owner'; permissions?: string[] }
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
    { view: 'signup', signupPanel: 'register', label: 'Sign up', icon: 'signup' },
    { view: 'signup', signupPanel: 'saved', label: 'My signups', icon: 'signup' },
    { view: 'assignments', label: 'My clan assignments', icon: 'shield' },
  ] },
  { id: 'staff-overview', label: 'Staff', icon: 'overview', items: [
    { view: 'staff-overview', label: 'Staff overview', icon: 'overview', permissions: ['cwl','cwl_signups','cwl_roster','cwl_publish','cwl_reminders','cwl_results','cwl_bonuses','cwl_send','cwl_settings','clan_weights','clans','text_commands','recruitment','tickets','member_roles','fwa','server_tools'] },
  ] },
  { id: 'cwl-management', label: 'CWL', icon: 'trophy', access: 'staff', items: [
    { view: 'staff', permissions: ['cwl_settings'], label: 'Seasons', icon: 'settings' },
    { view: 'reminders', permissions: ['cwl_reminders'], label: 'Signup reminders', icon: 'mail' },
    { view: 'roster', permissions: ['cwl_roster', 'cwl_signups'], label: 'Build roster', icon: 'roster' },
    { view: 'publication', step: 'review', permissions: ['cwl_publish'], label: 'Finalize roster', icon: 'publish' },
    { view: 'publication', step: 'announce', permissions: ['cwl_send'], label: 'Announcements', icon: 'mail' },
    { view: 'declaration', permissions: ['cwl_roster'], label: 'Declaration readiness check', icon: 'tasks' },
    { view: 'cwl-returns', permissions: ['cwl_reminders'], label: 'Return reminders', icon: 'return' },
    { view: 'participation', permissions: ['cwl_results'], label: 'Results & participation', icon: 'results' },
    { view: 'bonuses', permissions: ['cwl_bonuses', 'cwl_send'], label: 'Bonus medals', icon: 'medal' },
    { view: 'exports', permissions: ['cwl_results'], label: 'Exports & history', icon: 'download' },
  ] },
  { id: 'clans', label: 'Clan management', icon: 'shield', items: [
    {view:'clan-management',label:'Family clans',icon:'shield',permissions:['clans']},
    {view:'weight-trial',label:'Clan weights',icon:'roster',permissions:['clan_weights']},
    {view:'strikes',label:'Strikes',icon:'flag',permissions:['strikes','strikes_add','strikes_remove']},
    {view:'replacements',label:'Replacements',icon:'replace',permissions:['strikes','strikes_add','strikes_remove']},
  ] },
  { id: 'tickets', label: 'Tickets', icon: 'mail', items: [
    { view: 'tickets', label: 'Browse tickets', icon: 'ticket', permissions: ['tickets'] },
  ] },
  { id: 'server-tools', label: 'Server tools', icon: 'tools', items: [
    { view: 'members-settings', label: 'Members & roles', icon: 'users', permissions: ['member_roles'] },
    { view: 'moderation', label: 'Moderation', icon: 'flag', permissions: ['member_roles'] },
    { view: 'applications-settings', label: 'Applications & tickets', icon: 'mail', permissions: ['recruitment','tickets'] },
    { view: 'fwa-settings', label: 'FWA tools', icon: 'war', permissions: ['fwa'] },
    { view: 'text-commands', label: 'Command triggers', icon: 'command', permissions: ['text_commands'] },
  ] },
  { id: 'settings', label: 'Settings', icon: 'settings', items: [
    { view: 'image-gallery', label: 'Image Gallery', icon: 'image', permissions: ['text_commands'] },
    { view: 'connections-settings', label: 'Integrations', icon: 'connect', permissions: ['server_tools'] },
    { view: 'issues', label: 'Dashboard issues', icon: 'settings', access: 'owner' },
    { view: 'access', label: 'Staff access', icon: 'users', access: 'owner' },
  ] },
]
// Navigation mirrors explicit grants; every API still checks authorization.
export function visibleNavigationSections(canEdit: boolean, isOwner: boolean, permissions: string[] = []) {
  return sections.filter(section => !section.access || (section.access === 'staff' ? canEdit : isOwner))
    .map(section => ({ ...section, items: section.items.filter(item =>
      (item.access !== 'owner' || isOwner) && (isOwner || !item.permissions || item.permissions.some(scope => (permissions.includes(scope) || (scope.startsWith('cwl_') && permissions.includes('cwl')))))) }))
    .filter(section => section.items.length > 0)
}
export function navigationLabel(view: DashboardView, step: 'review' | 'announce' = 'review'): string {
  if (view === 'publication') return step === 'announce' ? 'Announcements' : 'Finalize roster'
  if (view === 'member-activity') return 'Moderation'
  return sections.flatMap(section => section.items).find(item => item.view === view)?.label
    || (view === 'manage' ? 'Server management' : 'Dashboard')
}
export function navigationSection(view: DashboardView) {
  if (view === 'member-activity') return navigationSection('moderation')
  return sections.find(section => section.items.some(item => item.view === view))?.label
}
export default function SidebarNavigation({ userId, view, canEdit, isOwner, permissions = [], onNavigate, publicationStep = "review", onPublication, signupPanel = 'register', onSignup, tourExpanded = false }: {
  userId: string; view: DashboardView; canEdit: boolean; isOwner: boolean; permissions?: string[]; onNavigate: (view: DashboardView) => void; publicationStep?: "review" | "announce"; onPublication?: (step: "review" | "announce") => void; signupPanel?: 'register' | 'saved'; onSignup?: (panel: 'register' | 'saved') => void; tourExpanded?: boolean
}) {
  const key = `wu-navigation-v3:${userId}`
  const cwlToggled = useRef(false)
  const [staffExpanded, setStaffExpanded] = useState(() => {
    const active = sections.find(section => section.items.some(item => item.view === view))
    return !!active && !['my-dashboard', 'activity', 'my-cwl'].includes(active.id)
  })
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    try {
      const current = localStorage.getItem(key)
      const saved = JSON.parse(current || localStorage.getItem(`wu-navigation-v2:${userId}`) || '{}')
      const carried = Object.fromEntries(
        Object.entries(saved || {}).filter(([id, value]) =>
          typeof value === 'boolean' && (id !== 'my-cwl' || current !== null)),
      ) as Record<string, boolean>
      cwlToggled.current = typeof carried['my-cwl'] === 'boolean'
      return {
        ...carried,
        ...Object.fromEntries(sections.map(section => [section.id,
          typeof carried[section.id] === 'boolean'
            ? carried[section.id] : ['my-dashboard', 'my-cwl'].includes(section.id),
        ])),
      }
    } catch { return { 'my-dashboard': true, 'my-cwl': true } }
  })
  useEffect(() => {
    const active = sections.find(section => section.items.some(item => item.view === view))
    if (active && !['my-dashboard', 'activity', 'my-cwl'].includes(active.id)) setStaffExpanded(true)
    const group = ['participation','bonuses','exports'].includes(view) ? 'cwl-results' : null
    if (group) setExpanded(current => ({...current,[group]:true}))
    if (active && active.id !== 'my-cwl') setExpanded(current => ({ ...current, [active.id]: true }))
  }, [view])
  useEffect(() => {
    try {
      const saved = {...expanded}
      if (!cwlToggled.current) delete saved['my-cwl']
      localStorage.setItem(key, JSON.stringify(saved))
    } catch { /* Preferences are optional. */ }
  }, [expanded, key])
  const itemActive = (item: Item) => view === item.view && (!item.step || item.step === publicationStep) && (!item.signupPanel || item.signupPanel === signupPanel)
  const itemButton = (item: Item) => <button data-tour-target={item.signupPanel || item.view} key={`${item.view}:${item.step || item.signupPanel || ""}`} aria-current={itemActive(item) ? 'page' : undefined} onClick={() => item.signupPanel && onSignup ? onSignup(item.signupPanel) : item.step && onPublication ? onPublication(item.step) : onNavigate(item.view)}><span className="navigation-icon" aria-hidden="true"><DashboardIcon name={item.icon} /></span><span>{item.label}</span></button>
  const visible = visibleNavigationSections(canEdit, isOwner, permissions)
  const memberSections = visible.filter(section => ['my-dashboard', 'activity', 'my-cwl'].includes(section.id))
  const staffSections = visible.filter(section => !['my-dashboard', 'activity', 'my-cwl'].includes(section.id))
  const renderSection = (section: Section) => {
    if (['my-dashboard', 'activity', 'staff-overview'].includes(section.id)) {
        return <section className="navigation-section navigation-everyday" key={section.id}>
          {section.id !== 'my-dashboard' && <h2 className="navigation-label">{section.label}</h2>}
          {section.items.map(itemButton)}
        </section>
      }
      const active = section.items.some(item => item.view === view)
      return <section className={`navigation-section${active ? ' contains-current' : ''}`} key={section.id}>
        <button className="navigation-toggle" aria-expanded={!!expanded[section.id] || (tourExpanded && section.id === 'my-cwl')} aria-controls={`navigation-${section.id}`} onClick={() => { if (section.id === 'my-cwl') cwlToggled.current = true; setExpanded(current => ({ ...current, [section.id]: !current[section.id] })) }}>
          <span className="navigation-icon" aria-hidden="true"><DashboardIcon name={section.icon} /></span><span>{section.label}</span><span className="navigation-chevron" aria-hidden="true"><DashboardIcon name={expanded[section.id] ? "chevronDown" : "chevronRight"} /></span>
        </button>
        <div id={`navigation-${section.id}`} className="navigation-children" hidden={!expanded[section.id] && !(tourExpanded && section.id === 'my-cwl')}>{section.id === 'cwl-management' ? <>
          {section.items.filter(item => !['participation','bonuses','exports'].includes(item.view)).map(itemButton)}
          {section.items.some(item => ['participation','bonuses','exports'].includes(item.view)) && <div>
            <button className="navigation-toggle" aria-expanded={!!expanded['cwl-results']} aria-controls="cwl-results" onClick={() => setExpanded(current => ({...current,'cwl-results':!current['cwl-results']}))}>
              <span className="navigation-icon"><DashboardIcon name="medal" /></span><span>Results</span>
              <span className="navigation-chevron" aria-hidden="true"><DashboardIcon name={expanded['cwl-results'] ? 'chevronDown' : 'chevronRight'} /></span>
            </button>
            <div id="cwl-results" className="navigation-children" hidden={!expanded['cwl-results']}>
              {section.items.filter(item => ['participation','bonuses','exports'].includes(item.view)).map(itemButton)}
            </div>
          </div>}
        </> : section.id === 'clans' ? <>
          {section.items.filter(item => ['clan-management','weight-trial'].includes(item.view)).map(itemButton)}
          {section.items.some(item => item.view === 'strikes') && <div className="strikes-nav-group">
            {section.items.filter(item => item.view === 'strikes').map(itemButton)}
            <div className="navigation-children strikes-subnav">{section.items.filter(item => item.view === 'replacements').map(itemButton)}</div>
          </div>}
        </> : section.items.map(itemButton)}</div>
      </section>
  }
  return <nav aria-label="Warriors United navigation">
    {memberSections.map(renderSection)}
    {staffSections.length > 0 && <section className={`navigation-section navigation-staff${staffSections.some(section => section.items.some(item => itemActive(item))) ? ' contains-current' : ''}`}>
      <button className="navigation-toggle" aria-expanded={staffExpanded} aria-controls="navigation-staff-tools" onClick={() => setStaffExpanded(current => !current)}>
        <span className="navigation-icon" aria-hidden="true"><DashboardIcon name="tools" /></span><span>Staff tools</span>
        <span className="navigation-chevron" aria-hidden="true"><DashboardIcon name={staffExpanded ? 'chevronDown' : 'chevronRight'} /></span>
      </button>
      <div id="navigation-staff-tools" className="navigation-children navigation-staff-children" hidden={!staffExpanded}>
        {staffSections.map(renderSection)}
      </div>
    </section>}
  </nav>
}
