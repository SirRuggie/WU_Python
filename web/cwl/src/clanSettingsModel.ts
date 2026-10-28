import type { Pool } from "./api";
import type { RosterClan } from "./roster";

export type ClanRules = {
  pool: Pool;
  capacity: number;
  min_weight: number | null;
  max_weight: number | null;
};

export function settingsClans(clans: RosterClan[], pool: Pool) {
  return clans.filter(
    (clan) => !clan.archived && (!clan.pool || clan.pool === pool),
  );
}

export function poolChangeReason(clan: RosterClan, pool: Pool) {
  return clan.pool && clan.pool !== pool && clan.assigned_count > 0
    ? `Can't move to ${pool === "main" ? "Main" : "Lazy"} CWL: ${clan.assigned_count} players are assigned here. Assign them elsewhere first.`
    : "";
}
