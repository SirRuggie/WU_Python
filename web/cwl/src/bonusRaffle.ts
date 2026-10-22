import type { Pool } from './api'
import type { BonusAccount, BonusData } from './bonus'

export type RaffleAccount = BonusAccount & { season_rounds?: number | null; exclusion?: string; attacks_override?: boolean }
export type BonusAllowance = {
  status: 'ready' | 'pending' | 'unavailable'; total: number | null; base: number | null;
  wins: number; completed_wars: number; rounds: number | null; league: string | null;
  team_size: number | null; reason: string; rules_version: string;
}
export type RafflePreview = {
  allowance_source?: 'automatic' | 'staff'; allowance?: BonusAllowance | null;
  cycle: string; pool: Pool; clan_tag: string; clan_name: string;
  minimum: number; slots: number; available: number; confirmed: number;
  eligible: RaffleAccount[]; excluded: RaffleAccount[]; blocking_reasons: string[];
  fingerprint: string;
}
export type SavedDraw = {
  id: number; pool: Pool; clan_tag: string; cycle: string; created_at: string;
  approved_at: string | null; cancelled_at: string | null; cancel_reason: string | null; snapshot: RafflePreview & { winners: RaffleAccount[] };
  messages: string[];
  delivery: null | {
    channel_id: string; status: string; failure: string | null;
    pages: { page: number; status: string; message_id: string | null }[];
  };
}
export type RaffleData = BonusData & {
  season_status: string; historical_accounts_count: number; sync: {enabled: boolean; last_checked_at: string | null; warning: string | null}; roster_source: string; policies: Record<Pool, number | null>;
  draws: SavedDraw[]; accounts: RaffleAccount[]; allowances?: Record<string, BonusAllowance>;
}
export const attacksText = (account: RaffleAccount) => account.attacks === null
  ? 'Not Available'
  : `${account.attacks}${account.season_rounds ? `/${account.season_rounds}` : ''} attacks${account.attacks_override ? ' · Staff correction' : ''}`
