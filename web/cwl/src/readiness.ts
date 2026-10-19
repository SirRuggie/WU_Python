import type { RosterAccount, RosterClan } from './roster'
export type ReadinessFilter = 'all' | 'unassigned' | 'missing_weight' | 'over_capacity'
export function readinessAccounts(accounts: RosterAccount[], clans: RosterClan[], filter: ReadinessFilter) {
  const counts = new Map<string, number>()
  for (const account of accounts) if (account.assigned_clan_tag) counts.set(account.assigned_clan_tag, (counts.get(account.assigned_clan_tag) || 0) + 1)
  const full = new Set(clans.filter(clan => (counts.get(clan.tag) || 0) > clan.effective_capacity).map(clan => clan.tag))
  return accounts.filter(account => filter === 'all' || (filter === 'unassigned' ? !account.assigned_clan_tag : filter === 'missing_weight' ? account.effective_weight == null : !!account.assigned_clan_tag && full.has(account.assigned_clan_tag)))
}
