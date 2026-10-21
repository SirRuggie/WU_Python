import type { Account } from './api'
export type SearchResult = { kind: 'player' | 'clan'; tag: string; name: string; detail: string; townHall?: number | null }
export function searchIndex(accounts: Account[], family: {tag: string; name: string}[]): SearchResult[] {
  const clans = new Map<string, SearchResult>()
  for (const clan of family) clans.set(clan.tag, {kind: 'clan', tag: clan.tag, name: clan.name, detail: 'Family clan'})
  for (const account of accounts) {
    if (account.current_clan_tag && !clans.has(account.current_clan_tag)) clans.set(account.current_clan_tag, {kind:'clan', tag:account.current_clan_tag, name:account.current_clan_name || account.current_clan_tag, detail:'Clan of a linked account'})
  }
  return [...accounts.map(account => ({kind:'player' as const, tag:account.tag, name:account.name, detail:account.current_clan_name || 'No current clan', townHall:account.town_hall})), ...clans.values()]
}
export function matchingResults(index: SearchResult[], query: string, kind: 'all' | 'player' | 'clan') {
  const needle = query.trim().toLocaleLowerCase().replace(/^#/, '')
  return index.filter(item => (kind === 'all' || item.kind === kind) && `${item.name} ${item.tag} ${item.detail}`.toLocaleLowerCase().includes(needle))
}
