import { sortRosterAccounts, type RosterAccount, type RosterSort } from './roster'
export type ClanSummary = { count: number; knownTownHalls: number; averageTownHall: number | null; knownWeights: number; averageWeight: number | null }
export function compareClanAccounts(accounts: RosterAccount[], clanTag: string, sort: RosterSort): RosterAccount[] {
  return sortRosterAccounts(accounts.filter(account => account.assigned_clan_tag === clanTag), sort)
}
export function clanSummary(accounts: RosterAccount[], clanTag: string): ClanSummary {
  const members = accounts.filter(account => account.assigned_clan_tag === clanTag)
  const halls = members.map(account => account.town_hall).filter((value): value is number => value !== null)
  const weights = members.map(account => account.effective_weight).filter((value): value is number => value !== null)
  return { count: members.length, knownTownHalls: halls.length, averageTownHall: halls.length ? halls.reduce((a, b) => a + b, 0) / halls.length : null, knownWeights: weights.length, averageWeight: weights.length ? weights.reduce((a, b) => a + b, 0) / weights.length : null }
}

// Keep staff choices stable when hosting clans or filters change.
export function comparisonOrder(saved: unknown, available: string[]): string[] {
  if (!Array.isArray(saved)) return available.slice(0, 4)
  return [...new Set(saved.filter((tag): tag is string => typeof tag === 'string' && available.includes(tag)))].slice(0, 10)
}
export function moveComparisonClan(order: string[], tag: string, neighbor: string | undefined): string[] {
  if (!neighbor || !order.includes(tag) || !order.includes(neighbor)) return order
  return order.map(value => value === tag ? neighbor : value === neighbor ? tag : value)
}
