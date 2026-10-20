export type ReplacementGroup<T> = { tag: string; name: string; accounts: T[] }

export function groupReplacements<T extends { clan_tag?: string | null; clan_name?: string | null }>(candidates: T[]): ReplacementGroup<T>[] {
  const groups = new Map<string, ReplacementGroup<T>>()
  for (const candidate of candidates) {
    const tag = candidate.clan_tag || 'unknown'
    const group = groups.get(tag) || { tag, name: candidate.clan_name || 'No clan', accounts: [] }
    group.accounts.push(candidate)
    groups.set(tag, group)
  }
  return [...groups.values()]
}

export type RosterAccount = { player_tag: string; player_name: string; is_manual: boolean }

export function selectableTags(accounts: RosterAccount[]): string[] {
  return accounts.filter(account => !account.is_manual).map(account => account.player_tag)
}

export function toggleRosterTag(selected: string[], tag: string, accounts: RosterAccount[]): string[] {
  if (!selectableTags(accounts).includes(tag)) return selected
  return selected.includes(tag) ? selected.filter(value => value !== tag) : [...selected, tag]
}

export function bulkSaveMessage(result: { added_count: number; skipped_count: number }): string {
  return `${result.added_count} ${result.added_count === 1 ? 'account' : 'accounts'} added.${result.skipped_count ? ` ${result.skipped_count} already listed.` : ''}`
}

export function compactWeight(value: number): string {
  return `${Number((value / 1000).toFixed(3))}k`
}
export function enteredWeight(value: string): number {
  const amount = Number(value)
  return amount < 1000 ? amount * 1000 : amount
}
