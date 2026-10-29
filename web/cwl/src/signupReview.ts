import type { Account, Pool, Signup } from "./api";
import { reconcileNewSignupDraft, type Draft } from "./signup";

/** Retain only still-linked, unsigned accounts eligible for the chosen pool. */
export function reviewPoolSelection(
  draft: Draft,
  pool: Pool,
  accounts: Account[],
  signups: Signup[],
) {
  const unsigned = reconcileNewSignupDraft(draft, accounts, signups);
  const retained = Object.fromEntries(
    Object.entries(unsigned).filter(
      ([tag]) =>
        pool !== "main" ||
        accounts.find((account) => account.tag === tag)?.current_clan_type !==
          "FWA",
    ),
  );
  const removed = Object.keys(draft)
    .filter((tag) => !Object.hasOwn(retained, tag))
    .map((tag) => accounts.find((account) => account.tag === tag)?.name || tag);
  return { retained, removed };
}
