import {
  comparisonLocation,
  mergeComparisonLocations,
  type LocationRecords,
} from "./comparisonLocation";
import type { MemberAssignment, MyAssignments } from "./publication";

/** Keep verified locations across refreshes, pruning rows no longer visible. */
export function mergeAssignmentLocations(
  previous: LocationRecords,
  incoming: MyAssignments,
) {
  const merged = mergeComparisonLocations(
    previous,
    incoming.accounts.map((account) => ({
      ...account,
      current_clan_tag: account.current_clan_tag ?? null,
      current_clan_name: account.current_clan_name ?? null,
    })),
  );
  const records: LocationRecords = {};
  const accounts = incoming.accounts.map((account) => {
    if (merged[account.tag]) records[account.tag] = merged[account.tag];
    const state =
      incoming.published && account.assigned_clan_tag
        ? comparisonLocation(
            records[account.tag],
            account.assigned_clan_tag,
            Date.now(),
            account.assigned_clan_name || undefined,
          ).state
        : "unassigned";
    const arrival_status: MemberAssignment["arrival_status"] =
      state === "arrived"
        ? "arrived"
        : state === "missing"
          ? "missing"
          : state === "unassigned"
            ? "unassigned"
            : "unknown";
    return { ...account, arrival_status };
  });
  return { records, data: { ...incoming, accounts } };
}

export function assignmentArrivalLabel(accounts: MemberAssignment[]) {
  const arrived = accounts.filter(
    (account) => account.arrival_status === "arrived",
  ).length;
  const allKnown = accounts.every(
    (account) =>
      account.arrival_status === "arrived" ||
      account.arrival_status === "missing",
  );
  if (!arrived && !allKnown)
    return `${accounts.length} account${accounts.length === 1 ? "" : "s"}`;
  return arrived === accounts.length
    ? `All ${accounts.length} in clan`
    : `${arrived} of ${accounts.length} in clan`;
}
