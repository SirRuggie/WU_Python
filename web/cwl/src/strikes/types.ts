import type { ActivityAccount } from "../strikeActivityView";
import type { StrikeSettings } from "../StrikeSettingsEditor";
import type { StrikeStreakState } from "../StrikeStreak";

export type Tab = "history" | "leave" | "settings";
export type Clan = { tag: string; name: string; is_fwa?: boolean };
export type Account = {
  tag: string;
  name: string;
  current_clan_name?: string | null;
};
export type Member = { id: string; name: string; accounts: Account[] };
export type Entry = {
  id: string;
  war_key?: string | null;
  opponent_name?: string | null;
  player_tag: string;
  player_name: string;
  discord_id?: string | null;
  discord_name?: string | null;
  link_status?: string | null;
  current_clan_name?: string | null;
  current_clan_tag?: string | null;
  war_clan_name?: string | null;
  war_clan_tag?: string | null;
  war_end?: string | null;
  expires_at?: string | null;
  exemption?: string | null;
  kind: "strike" | "miss" | "completed" | "cwl" | "no_attack" | "mismatch";
  source: "war" | "manual" | "cwl";
  source_label?: string | null;
  war_type?: "regular" | "cwl";
  attacks_used?: number | null;
  attacks_per_member?: number | null;
  missed_attacks?: number | null;
  status:
    | "active"
    | "expired"
    | "removed"
    | "exempt"
    | "recorded"
    | "no_attack"
    | "mismatch"
    | "completed";
  reason?: string | null;
  war_plan_reason?: string | null;
  removed_reason?: string | null;
};
export type Overview = {
  entries: Entry[];
  clans: Clan[];
  total: number;
  streak?: StrikeStreakState | null;
};
export type StrikeAccount = Partial<ActivityAccount> & {
  left_clan?: boolean;
  last_clan_name?: string | null;
  departed_at?: string | null;
  player_tag: string;
  player_name: string;
  discord_id?: string | null;
  link_status?: string | null;
  current_clan_tag?: string | null;
  current_clan_name?: string | null;
  clan_is_current?: boolean;
  active_strikes: number;
  total_strikes: number;
  over_limit?: boolean;
  new_this_week?: boolean;
  last_strike_at?: string | null;
};
export type AccountOverview = {
  summary?: { over_limit: number; new_this_week: number };
  strike_limit?: number;
  accounts: StrikeAccount[];
  total: number;
  clans: Clan[];
};
export type War = {
  war_key: string;
  clan_tag: string;
  clan_name: string;
  opponent_tag?: string;
  opponent_name: string;
  war_end: string;
  missed_accounts: number;
  strikes: number;
  one_missed: number;
  no_attack?: number | boolean;
  mismatch?: number | boolean;
  war_plan_reason?: string | null;
  war_type?: "regular" | "cwl";
  cwl_missed?: number;
  source_label?: string | null;
  incomplete?: boolean;
  review_message?: string | null;
  manual_review_required?: boolean;
  review_revision?: number;
};
export type Settings = StrikeSettings;
export type ImportEntry = {
  key: string;
  player_tag: string;
  player_name: string;
  clan_name: string;
  war_end: string;
  missed_attacks: number;
  will_strike: boolean;
  kind?: string;
  source?: string;
  war_type?: "regular" | "cwl";
  attacks_used?: number | null;
  attacks_per_member?: number | null;
  discord_id?: string | null;
  link_status?: string | null;
  exempt?: boolean;
  duplicate?: boolean;
};
export type DeferredAccount = {
  player_tag: string;
  player_name: string;
  clan_name: string;
  war_end?: string | null;
  missed_attacks?: number;
  reason?: string;
  link_status?: string | null;
};
export type ImportResult = {
  added_strikes?: number;
  duplicates?: number;
  history_only?: number;
  excluded?: number;
  applied: number;
  strikes: number;
  skipped: number | unknown[];
  cwl_wars?: number;
  cwl_records?: number;
  cwl_missed?: number;
  deferred_count?: number;
  deferred_accounts?: DeferredAccount[];
};
export type ActiveImportJob = { job_id: string; phase: "preview" | "apply" };
export type ImportDraft = {
  job: ActiveImportJob | null;
  preview: ImportPreview | null;
  excluded: string[];
};
export type ImportPreview = {
  preview_id: string;
  wars_scanned: number;
  complete_wars: number;
  incomplete_wars: number;
  cwl_wars?: number;
  cwl_records?: number;
  cwl_missed?: number;
  entries: ImportEntry[];
  deferred_accounts?: DeferredAccount[];
  deferred_count?: number;
  coverage: {
    clan_name: string;
    earliest?: string;
    latest?: string;
    wars: number;
    error?: string;
    skipped?: number;
    processing_skipped_wars?: number;
    deferred_accounts?: number;
  }[];
};
