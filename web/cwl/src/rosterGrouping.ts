import type { RosterAccount } from './roster'

export function rosterMemberKey(account: RosterAccount): string {
  return account.user_id ? `member:${account.user_id}` : `unlinked:${account.tag}`
}

/** Keep each member together; an oversized member gets a page of their own. */
export function rosterAccountPages(accounts: RosterAccount[], grouped: boolean): RosterAccount[][] {
  if (!grouped) {
    return Array.from({ length: Math.ceil(accounts.length / 20) }, (_, index) =>
      accounts.slice(index * 20, (index + 1) * 20))
  }
  const groups = new Map<string, RosterAccount[]>()
  for (const account of accounts) {
    const key = rosterMemberKey(account)
    const group = groups.get(key) || []
    group.push(account)
    groups.set(key, group)
  }
  const pages: RosterAccount[][] = []
  let page: RosterAccount[] = []
  for (const group of groups.values()) {
    if (page.length && page.length + group.length > 20) {
      pages.push(page)
      page = []
    }
    page.push(...group)
  }
  if (page.length) pages.push(page)
  return pages
}
