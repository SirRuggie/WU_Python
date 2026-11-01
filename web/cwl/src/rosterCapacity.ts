import type { RosterAccount } from "./roster";

/** All seats count; only overflow beyond the explicit filler seats is a warning. */
export function rosterCapacity(
  count: number,
  fillers: number,
  capacity: number | null,
) {
  const fillerCount = Math.max(0, Math.min(count, fillers));
  const regularOverflow =
    capacity === null ? 0 : Math.max(0, count - fillerCount - capacity);
  const over = regularOverflow > 0;
  const full = capacity !== null && count === capacity && fillerCount === 0;
  return {
    count,
    fillerCount,
    regularOverflow,
    over,
    full,
    state: over ? "over" : full ? "full" : "room",
    barClass: over ? "is-over" : full ? "is-full" : "has-room",
    fillerLabel: fillerCount
      ? `+${fillerCount} filler${fillerCount === 1 ? "" : "s"}`
      : "",
  };
}
export function clanCapacity(
  accounts: RosterAccount[],
  tag: string,
  capacity: number | null,
) {
  const assigned = accounts.filter((a) => a.assigned_clan_tag === tag);
  return rosterCapacity(
    assigned.length,
    assigned.filter((a) => a.roster_filler).length,
    capacity,
  );
}
