export type Priority = "replace_first" | "high" | "normal";
export type Clan = { tag: string; name: string; is_fwa?: boolean };
export type Candidate = {
  player_tag: string;
  player_name: string;
  clan_tag?: string | null;
  clan_name?: string | null;
  priority?: Priority;
  note?: string | null;
  weight?: number | null;
  weight_difference?: number | null;
  revision: number;
  active_strikes: number;
  clan_is_current?: boolean;
  clan_seen_at?: string | null;
  departed?: boolean;
  last_seen_clan_tag?: string | null;
  last_seen_clan_name?: string | null;
  current_clan_name?: string | null;
  current_clan_tag?: string | null;
  last_seen_at?: string | null;
  is_manual?: boolean;
  is_filler?: boolean;
};
export type GroupSummary = {
  clan_tag: string;
  clan_name: string;
  listed: number;
  at_three: number;
  chopping_block: number;
};
export type Result = {
  candidates: Candidate[];
  clans?: Clan[];
  top?: Candidate[];
  groups?: GroupSummary[];
  total?: number;
  town_halls?: number[];
};
