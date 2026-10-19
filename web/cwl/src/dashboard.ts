import type { Account, Signup } from './api'
import type { MemberAssignment } from './publication'
export type AccountFilter = 'all' | 'unsigned' | 'waiting' | 'assigned'
export function dashboardRows(accounts: Account[], signups: Signup[], assignments: MemberAssignment[]) {
  const saved = new Map(signups.map(item => [item.tag, item]))
  const placed = new Map(assignments.map(item => [item.tag, item]))
  return accounts.map(account => ({ ...account, signup: saved.get(account.tag), assignment: placed.get(account.tag) }))
}
export function filterDashboardRows(rows: ReturnType<typeof dashboardRows>, filter: AccountFilter, search: string, sort: string) {
  const query = search.trim().toLocaleLowerCase()
  return rows.filter(row => (filter === 'all' || (filter === 'unsigned' ? !row.signup : filter === 'assigned' ? !!row.assignment?.assigned_clan_tag : !!row.signup && !row.assignment?.assigned_clan_tag))
    && (!query || [row.name, row.tag, row.current_clan_name, row.assignment?.assigned_clan_name].some(value => value?.toLocaleLowerCase().includes(query))))
    .sort((a,b) => sort === 'th' ? (b.town_hall || 0) - (a.town_hall || 0) || a.name.localeCompare(b.name) : a.name.localeCompare(b.name))
}
export function availableSelection(tags: string[], rows: ReturnType<typeof dashboardRows>) {
  const available = new Set(rows.filter(row => !row.signup).map(row => row.tag))
  return tags.filter(tag => available.has(tag))
}
