import type { DashboardIconName } from './DashboardIcon'
import type { Account } from './api'
export type TodoKind = 'war' | 'cwl' | 'raid' | 'games' | 'private'
export type TodoRow = { tag: string; name: string; town_hall: number | null; clan_tag: string | null; clan_name: string | null; badge_url?: string | null; used: number | null; total: number | null; remaining: number | null; starts_at: number | null; ends_at: number | null; state: string; detail: string | null; fwa_outcome?: { status: 'win' | 'lose' | 'blacklisted' | 'unknown'; opponent: string } | null }
export type TodoView = { loading?: boolean; season?: string; source?: string; checked_at?: string; event_start?: number; event_end?: number; ok: boolean; note: string; notes: string[]; unavailable: string; incomplete: string; rows: TodoRow[] }
export type TodoSnapshot = { checked_at: string; accounts: Account[]; views: Record<TodoKind, TodoView> }
export const todoTabs: { key: TodoKind; icon: DashboardIconName; label: string; description: string }[] = [
  { key: 'war', icon: 'war', label: 'War', description: 'Regular-war attacks still to use, including upcoming preparation days.' },
  { key: 'cwl', icon: 'trophy', label: 'CWL', description: 'CWL attacks still to use. This is your live war activity, separate from season signups.' },
  { key: 'raid', icon: 'raid', label: 'Raids', description: 'Capital Raid attacks still to use for the current raid weekend.' },
  { key: 'games', icon: 'games', label: 'Clan Games', description: 'Points earned by each account for this month’s Clan Games.' },
  { key: 'private', icon: 'locked', label: 'Cannot check', description: 'Accounts whose war activity needs checking in-game because a log is private or unavailable.' },
]
export function visibleTodoRows(rows: TodoRow[], selected: string[] | null, search: string, sort: string, exactTag = false) {
  const query = search.trim().toLocaleLowerCase()
  return rows.filter(row => (selected === null || selected.includes(row.tag)) && (!query || (exactTag ? [row.tag, row.clan_tag].some(value => value?.toLocaleLowerCase() === query) : [row.name,row.tag,row.clan_name,row.clan_tag].some(value => value?.toLocaleLowerCase().includes(query)))))
    .sort((a,b) => sort === 'th' ? (b.town_hall || 0) - (a.town_hall || 0) || a.name.localeCompare(b.name) : sort === 'name' ? a.name.localeCompare(b.name) : (a.ends_at ?? Infinity) - (b.ends_at ?? Infinity) || a.name.localeCompare(b.name))
}
export function todoEmptyText(view: TodoView, kind: TodoKind, filtered: boolean) {
  if (!view.ok || view.incomplete) return 'Some activity could not be checked. This does not mean your tasks are complete.'
  if (view.unavailable) return view.unavailable
  if (filtered) return 'No tasks match these account filters.'
  if (kind === 'games') return 'No Clan Games scores are available for these accounts. Check your progress in-game.'
  if (kind === 'private') return 'No unreadable war logs were found in this check.'
  return 'No outstanding tasks found in the activity we could check.'
}
export function todoTime(epoch: number | null, now: number) {
  if (!epoch) return 'Time unavailable'
  const seconds = epoch - now / 1000
  if (seconds <= 0) return 'Time passed · check latest status'
  const minutes = Math.ceil(seconds / 60)
  const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60), mins = minutes % 60
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${mins}m` : `${mins}m`
}
