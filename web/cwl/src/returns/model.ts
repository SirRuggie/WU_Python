import type { ManagementSection } from '../serverManagement'
export type ReturnClan = ManagementSection & { return_section?: 'MAIN'|'FWA'; clan_tag?: string; clan_name?: string }
export type ReturnAction = 'save'|'start'|'schedule'|'pause'|'resume'|'send'|'away'
export const actionLabels: Record<ReturnAction,string> = {
  save:'Capture current members', start:'Start return reminders', schedule:'Schedule for later', pause:'Pause',
  resume:'Resume', send:'Send now', away:'Check away players',
}
export function clanSection(row: ReturnClan): 'MAIN'|'FWA' {
  return row.return_section || (row.id.startsWith('MAIN') ? 'MAIN' : 'FWA')
}
export function clanKey(row: ReturnClan) { return `${clanSection(row)}:${row.clan_tag || row.id.replace(/^(MAIN|FWA)/,'')}` }
export function canApply(row: ReturnClan, action: ReturnAction) {
  const state = row.return_status?.state
  if (action === 'save') return state === 'not_saved'
  if (action === 'start' && state === 'not_saved') return clanSection(row) === 'FWA'
  if (!state || state === 'not_saved' || state === 'expired') return false
  return !['start','schedule','pause','resume'].includes(action) || clanSection(row) === 'FWA'
}
export function localDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)
}
export function scheduleValues(start: string, end: string) {
  const first = new Date(start), last = new Date(end)
  if (!start || !end || Number.isNaN(first.getTime()) || Number.isNaN(last.getTime())) throw new Error('Choose both start and end dates.')
  if (last <= first || last.getTime() <= Date.now()) throw new Error('End must be after start and still in the future.')
  if (last.getTime()-first.getTime() > 7*86400000) throw new Error('Choose a window of up to seven days.')
  return {schedule_start:first.toISOString(), schedule_end:last.toISOString()}
}
export function displayDate(value?: string|null) { return value ? new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) : 'Not set' }
