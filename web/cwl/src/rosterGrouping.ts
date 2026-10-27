import type { RosterAccount } from "./roster";

export function rosterMemberKey(account: RosterAccount): string {
  return account.user_id
    ? `member:${account.user_id}`
    : `unlinked:${account.tag}`;
}
