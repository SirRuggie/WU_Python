import type {ManagementSection} from './serverManagement'
export const managementAreas = {
  'members-settings': {title:'Members & roles',description:'Find members and manage their roles.'},
  'applications-settings': {title:'Applications & tickets',description:'Set up the applicant journey and staff tools. Review live conversations in Tickets.'},
  'fwa-settings': {title:'FWA tools',description:'Manage war messages, bases and clan settings.'},
  'connections-settings': {title:'Integrations',description:'Check connected services and technical settings.'},
  'cwl-returns': {title:'Return reminders',description:'Manage saved CWL clans and reminders to return home.'},
} as const
export type ManagementArea = keyof typeof managementAreas
export function isManagementArea(value:string):value is ManagementArea {return Object.hasOwn(managementAreas,value)}
export function sectionArea(section:ManagementSection):ManagementArea|null {
  if(section.id==='roles')return 'members-settings'
  if(section.id==='band_monitor')return 'connections-settings'
  if(section.id==='cwl_rosters'||section.id.startsWith('cwl-'))return 'cwl-returns'
  if(section.id.startsWith('fwa_')||section.id.startsWith('war--'))return 'fwa-settings'
  if(section.id.startsWith('ticket_')||/^(gauntlet|destination|question|staff|publish)--/.test(section.id))return 'applications-settings'
  return null
}
export function areaSections(sections:ManagementSection[], area:ManagementArea) {
  return sections.filter(section=>section.allowed!==false&&sectionArea(section)===area&&!section.destination).map(section=>{
    let group=section.group
    if(area==='applications-settings')group=section.id==='ticket_testing'?'Testing':section.id==='ticket_settings'||section.id.startsWith('destination--')?'Channels & access':section.id.startsWith('question--')?'Questions':section.id.startsWith('staff--')?'Staff messages':'Messages'
    if(area==='fwa-settings')group=section.id.startsWith('war--')?'War messages':'Clan tools'
    return {...section,group}
  })
}
