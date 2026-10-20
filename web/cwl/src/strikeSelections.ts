export type ImportSelection = { key: string; will_strike: boolean; duplicate?: boolean; exempt?: boolean }

export function selectedImportEntries<T extends ImportSelection>(entries: T[], excluded: string[]): T[] {
  const blocked = new Set(excluded)
  return entries.filter(item => !item.duplicate && !blocked.has(item.key))
}

export function defaultLeaveTags(accounts: { tag: string }[]): string[] {
  return accounts.map(account => account.tag)
}

export function toggleLeaveTag(tags: string[], tag: string, checked: boolean): string[] {
  return checked ? [...new Set([...tags, tag])] : tags.filter(value => value !== tag)
}
