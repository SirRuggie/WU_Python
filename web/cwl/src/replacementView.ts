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
