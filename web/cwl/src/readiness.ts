import type { RosterAccount, RosterClan } from "./roster";
import { clanCapacity } from "./rosterCapacity";
export type ReadinessFilter =
  "all" | "unassigned" | "missing_weight" | "over_capacity";
export function readinessAccounts(
  accounts: RosterAccount[],
  clans: RosterClan[],
  filter: ReadinessFilter,
) {
  const over = new Set(
    clans
      .filter((c) => clanCapacity(accounts, c.tag, c.effective_capacity).over)
      .map((c) => c.tag),
  );
  return accounts.filter(
    (a) =>
      filter === "all" ||
      (filter === "unassigned"
        ? !a.assigned_clan_tag
        : filter === "missing_weight"
          ? a.effective_weight == null
          : !!a.assigned_clan_tag && over.has(a.assigned_clan_tag)),
  );
}
