export type DeclarationExtraClan = {
  tag: string;
  name: string;
  capacity: number | null;
  status: "current" | "unavailable";
  checked_at: string | null;
  count: number | null;
  extras:
    | {
        tag: string;
        name: string;
        town_hall: number | null;
        context: string;
        assigned_clan_tag: string | null;
      }[]
    | null;
};
export type DeclarationExtraResponse = {
  source: "draft" | "published";
  basis: number;
  clans: DeclarationExtraClan[];
};
