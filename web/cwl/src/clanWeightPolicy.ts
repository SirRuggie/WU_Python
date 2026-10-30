import type { RosterAccount } from "./roster";

/** Saved clan weights and current FWA members use the same editor. */
export function usesClanWeights(account: {
  clan_weight_managed?: boolean;
  current_fwa_clan_tag?: string | null;
}): boolean {
  return Boolean(account.clan_weight_managed || account.current_fwa_clan_tag);
}

/** Unknown is not evidence of leaving. Keep only this account/pool's known group. */
export function retainFwaMembership(
  previous: RosterAccount | undefined,
  incoming: RosterAccount,
): Pick<RosterAccount, "current_fwa_clan_tag" | "current_fwa_status"> {
  const retain =
    previous &&
    previous.tag === incoming.tag &&
    previous.pool === incoming.pool &&
    ["current", "stale"].includes(previous.current_fwa_status || "") &&
    incoming.current_fwa_status === "unavailable" &&
    !(
      incoming.current_clan_status === "current" &&
      incoming.current_clan_tag !== previous.current_clan_tag
    );
  return retain
    ? {
        current_fwa_clan_tag: previous.current_fwa_clan_tag,
        current_fwa_status: "stale",
      }
    : {
        current_fwa_clan_tag: incoming.current_fwa_clan_tag,
        current_fwa_status: incoming.current_fwa_status,
      };
}
