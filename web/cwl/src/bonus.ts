import type { Pool } from './api'

export type BonusPolicy = { min_attacks: number | null; min_stars: number | null; cooldown_months: number | null }
export type BonusClan = { tag: string; name: string; slots: number | null }
export type PreviousBonus = { cycle: string; confirmed_at: string; season_id: number; clan_tag: string | null }
export type BonusAccount = {
  tag: string; player_name: string; pool: Pool; assigned_clan_tag: string | null; assigned_clan_name: string | null;
  attacks: number | null; stars: number | null; source_status: string; source_warning: string | null;
  last_confirmed_bonus: PreviousBonus | null; recommended: boolean | null; eligibility_reason: string | null;
  source_complete: boolean; already_confirmed_this_cycle: boolean; selected: boolean; reason: string
}
export type BonusHistory = {
  id: number; tag: string; player_name: string; clan_tag: string | null; clan_name: string | null;
  cycle: string; publication_version: number; attacks: number | null; stars: number | null; reason: string;
  confirmed_by: string; confirmed_at: string; voided_by: string | null; voided_at: string | null; void_reason: string | null; warnings?: string[]
}
export type BonusData = { cycle: string | null; revision: number; policy: BonusPolicy; clans: BonusClan[]; accounts: BonusAccount[]; history: BonusHistory[]; cycle_confirmed: { id: number; tag: string; clan_tag: string | null; season_id: number }[]; active_other_cycles: string[]; history_scope: 'dashboard_confirmations_only'; award_status: string }
