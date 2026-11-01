import type { ArrivalResponse } from "./locationTransport";
import type { RosterAccount, RosterSnapshot } from "./roster";
import type { PublicationDraft } from "./publication";
export type DeclarationAccount = ArrivalResponse["accounts"][number] & {
  roster_filler?: boolean;
  roster_filler_revision?: number;
  player_name: string;
  user_id?: string | null;
  town_hall: number | null;
  pool: "main" | "lazy";
  hosting_pool: "main" | "lazy";
};
export type DeclarationArrival = Omit<ArrivalResponse, "accounts"> & {
  accounts: DeclarationAccount[];
  season_archived?: boolean;
  publication_available: boolean;
  publication_outdated: boolean;
  version: number | null;
  published_at: string | null;
};
export type DeclarationData = {
  arrival: DeclarationArrival;
  roster: RosterSnapshot;
  publication: PublicationDraft;
  publishedAccounts?: RosterAccount[];
};
/** A published identity/placement is never substituted with the working draft. */
export function declarationSnapshot(data: DeclarationData): RosterSnapshot {
  return {
    revision: data.roster.revision,
    undo: null,
    clans: data.roster.clans.map((clan) => ({
      ...clan,
      name:
        data.arrival.accounts.find((a) => a.assigned_clan_tag === clan.tag)
          ?.assigned_clan_name || clan.name,
    })),
    accounts: data.arrival.accounts.map((a): RosterAccount => ({
      ...a,
      user_id: a.user_id || "",
      prefer_crystal_1_or_lower: false,
      source_weight: null,
      source_status: "missing",
      source_name: null,
      source_checked_at: null,
      source_modified_at: null,
      manual_weight: null,
      effective_weight: null,
      ...data.publishedAccounts?.find((published) => published.tag === a.tag),
      roster_filler:
        data.roster.accounts.find((current) => current.tag === a.tag)
          ?.roster_filler ?? a.roster_filler,
      roster_filler_revision:
        data.roster.accounts.find((current) => current.tag === a.tag)
          ?.roster_filler_revision ?? a.roster_filler_revision,
      kept: Boolean(
        data.publishedAccounts?.find((published) => published.tag === a.tag)
          ?.kept,
      ),
      current_clan_status: undefined,
    })),
  };
}
