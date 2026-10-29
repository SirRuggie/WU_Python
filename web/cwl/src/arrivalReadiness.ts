import {
  comparisonLocation,
  type ComparisonLocation,
} from "./comparisonLocation";
export type ArrivalAccount = ComparisonLocation & {
  tag: string;
  assigned_clan_tag: string | null;
  assigned_clan_name?: string | null;
};
export function summarizeArrivalReadiness(
  accounts: readonly ArrivalAccount[],
  options: { now: number; capacity: number | null },
) {
  const assigned = accounts.filter((a) => a.assigned_clan_tag);
  const arrived = assigned.filter(
    (a) =>
      comparisonLocation(
        a,
        a.assigned_clan_tag!,
        options.now,
        a.assigned_clan_name || undefined,
      ).state === "arrived",
  );
  const freshCount = arrived.filter(
    (a) => options.now - Date.parse(a.current_clan_checked_at || "") <= 300000,
  ).length;
  const capacity =
    options.capacity === 15 || options.capacity === 30
      ? options.capacity
      : null;
  return {
    assignedCount: assigned.length,
    arrivedCount: arrived.length,
    freshCount,
    ready: capacity !== null && freshCount >= capacity,
    refreshToConfirm:
      capacity !== null && arrived.length >= capacity && freshCount < capacity,
    needed: capacity === null ? null : Math.max(0, capacity - arrived.length),
  };
}
