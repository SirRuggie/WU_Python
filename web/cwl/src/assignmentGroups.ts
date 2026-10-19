import type { MemberAssignment } from './publication'

export type AssignmentGroup = {
  key: string
  clanTag: string | null
  clanName: string
  accounts: MemberAssignment[]
}

export function groupAssignments(accounts: MemberAssignment[]): AssignmentGroup[] {
  const groups = new Map<string, AssignmentGroup>()
  for (const account of accounts) {
    const clanTag = account.assigned_clan_tag
    const key = clanTag || '__awaiting__'
    let group = groups.get(key)
    if (!group) {
      group = { key, clanTag, clanName: clanTag ? account.assigned_clan_name || clanTag : 'Awaiting placement', accounts: [] }
      groups.set(key, group)
    }
    if (clanTag && group.clanName === clanTag && account.assigned_clan_name) group.clanName = account.assigned_clan_name
    group.accounts.push(account)
  }
  return [...groups.values()].map(group => ({ ...group, accounts: [...group.accounts].sort((a, b) => a.player_name.localeCompare(b.player_name) || a.tag.localeCompare(b.tag)) })).sort((a, b) => {
    if (!a.clanTag) return 1
    if (!b.clanTag) return -1
    return a.clanName.localeCompare(b.clanName) || a.clanTag.localeCompare(b.clanTag)
  })
}
