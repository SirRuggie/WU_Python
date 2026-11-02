export type DeclarationExtraClan = {
  unpublished?: DeclarationExtraClan["extras"];
  unpublished_count?: number | null;
  low_th?: DeclarationExtraClan["extras"];
  fillers?: DeclarationExtraClan["extras"];
  tag: string;
  name: string;
  capacity: number | null;
  status: "current" | "unavailable";
  checked_at: string | null;
  count: number | null;
  extras:
    | {
        not_published_yet?: boolean;
        discord_id?: string;
        discord_profile?: import("./DiscordIdentity").DiscordProfile;
        roster_filler?: boolean;
        roster_filler_revision?: number;
        assigned_here?: boolean;
        tag: string;
        name: string;
        town_hall: number | null;
        context: string;
        assigned_clan_tag: string | null;
      }[]
    | null;
};
export type DeclarationExtraResponse = {
  revision?: number;
  source: "draft" | "published";
  basis: number;
  clans: DeclarationExtraClan[];
};
