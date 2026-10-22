import type { Pool } from './api'
import type { BonusAccount, BonusClan, BonusData } from './bonus'

export type BonusReview = {
  flags: string[];
  override_reason: string;
  revision?: number;
  updated_by?: string | null;
  updated_at?: string | null;
}

export type RaffleAccount = BonusAccount & {
  season_rounds?: number | null;
  exclusion?: string;
  attacks_override?: boolean;
  bonus_review?: BonusReview | null;
  manual_candidate?: boolean;
  manual_candidate_reason?: string | null;
  source?: string;
  multiplier?: number | null;
  three_cycle_cooldown?: boolean;
  cooldown_cycles?: string[];
  is_representative?: boolean;
  representative_status?: string;
}
export type BonusAllowance = {
  status: 'ready' | 'pending' | 'unavailable'; total: number | null; base: number | null;
  wins: number; completed_wars: number; rounds: number | null; league: string | null;
  team_size: number | null; reason: string; rules_version: string;
}
export type RafflePreview = {
  allowance_source?: 'automatic' | 'staff'; allowance?: BonusAllowance | null;
  cycle: string; pool: Pool; clan_tag: string; clan_name: string;
  minimum: number | null; qualification_rule?: string | null; rules_version?: number; slots: number; available: number; confirmed: number;
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
export type RaffleData = Omit<BonusData, 'accounts'> & {
  season_status: string; historical_accounts_count: number; sync: {enabled: boolean; last_checked_at: string | null; warning: string | null}; roster_source: string; policies: Record<Pool, number | null>;
  draws: SavedDraw[]; accounts: RaffleAccount[]; allowances?: Record<string, BonusAllowance>;
  lazy_settings?: { representative_role_id: string };
  bonus_reviews?: Record<string, BonusReview>;
  lazy_hosts?: BonusClan[];
}
export const attacksText = (account: RaffleAccount) => account.attacks === null
  ? 'Not Available'
  : `${account.attacks}${account.season_rounds ? `/${account.season_rounds}` : ''} attacks${account.attacks_override ? ' · Staff correction' : ''}`

export type BonusListMode = 'candidates' | 'eligible' | 'excluded' | 'winners'

export function bonusCandidateStatus(account: RaffleAccount, mode: BonusListMode): string {
  if (mode === 'winners') return ''
  if (account.exclusion) return account.exclusion
  if (mode === 'excluded') return 'Not included'
  if (account.bonus_review?.override_reason) return 'Included by staff exception'
  if (mode === 'eligible') return ''
  if (account.three_cycle_cooldown) return 'Three consecutive bonus seasons · sit out this season'
  return account.manual_candidate ? 'Added by staff · review eligibility' : ''
}

export type BonusDrawGuard = {
  canManage: boolean;
  busy: boolean;
  archived: boolean;
  policyDirty: boolean;
  roleDirty: boolean;
  reviewDirty: boolean;
  reviewOpen: boolean;
  candidateOpen: boolean;
  lookingUp: boolean;
  blocked: boolean;
}

export function canSaveBonusDraw(guard: BonusDrawGuard): boolean {
  return guard.canManage && !guard.busy && !guard.archived && !guard.policyDirty &&
    !guard.roleDirty && !guard.reviewDirty && !guard.reviewOpen && !guard.candidateOpen &&
    !guard.lookingUp && !guard.blocked
}
