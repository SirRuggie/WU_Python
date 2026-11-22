import type { Account, Pool, Signup } from "./api";
export type Draft = Record<string, boolean>;
export type SignupSelection = {
  tag: string;
  prefer_crystal_1_or_lower: boolean;
};

/** New signup selection never includes an account already saved in either pool. */
export function unsignedAccounts(
  accounts: Account[],
  signups: Signup[],
): Account[] {
  const signed = new Set(signups.map((row) => row.tag));
  return accounts.filter((account) => !signed.has(account.tag));
}
export function reconcileNewSignupDraft(
  draft: Draft,
  accounts: Account[],
  signups: Signup[],
): Draft {
  const available = new Set(
    unsignedAccounts(accounts, signups).map((account) => account.tag),
  );
  return Object.fromEntries(
    Object.entries(draft).filter(([tag]) => available.has(tag)),
  );
}
export function selectedEntries(
  accounts: Account[],
  draft: Draft,
): SignupSelection[] {
  return accounts
    .filter((account) => Object.hasOwn(draft, account.tag))
    .map((account) => ({
      tag: account.tag,
      prefer_crystal_1_or_lower: draft[account.tag],
    }));
}
export function submittedSummary(
  accounts: Account[],
  selected: SignupSelection[],
) {
  const byTag = new Map(accounts.map((account) => [account.tag, account]));
  return selected.map((item) => ({
    tag: item.tag,
    name: byTag.get(item.tag)?.name || item.tag,
    prefer_crystal_1_or_lower: item.prefer_crystal_1_or_lower,
  }));
}
export function clearSubmittedDraft(
  drafts: Record<Pool, Draft>,
  submittedPool: Pool,
): Record<Pool, Draft> {
  return { ...drafts, [submittedPool]: {} };
}

/** Signup-only display order; never mutates the provider account snapshot. */
export function sortSignupAccounts(accounts: Account[]): Account[] {
  return [...accounts].sort((left, right) => {
    const th = (value: Account) =>
      typeof value.town_hall === "number" && value.town_hall > 0
        ? value.town_hall
        : -1;
    return (
      th(right) - th(left) ||
      left.name.localeCompare(right.name, undefined, { sensitivity: "base" }) ||
      left.tag.localeCompare(right.tag)
    );
  });
}
