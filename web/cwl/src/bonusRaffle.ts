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
  season_status: string; historical_accounts_count: number; sync: {enabled: boolean; last_checked_at: string | null; warning: string | null; status?: string; cycle?: string | null}; roster_source: string; policies: Record<Pool, number | null>;
  draws: SavedDraw[]; accounts: RaffleAccount[]; allowances?: Record<string, BonusAllowance>;
  lazy_settings?: { representative_role_id: string };
  bonus_reviews?: Record<string, BonusReview>;
  lazy_hosts?: BonusClan[];
}
/** Card tally value: attacks over CWL rounds when known; "—" when not captured. */
export const attacksTally = (account: RaffleAccount) => account.attacks === null
  ? '—'
  : `${account.attacks}${account.season_rounds ? `/${account.season_rounds}` : ''}`

/** Reasons that apply to a whole hosting clan. They show once, above the list. */
export const CLAN_WIDE_REASONS: Record<string, string> = {
  'Hosting clan is no longer an active Lazy clan in this season': 'Hosting clan is not an active Lazy clan this season',
  'Complete participation results are unavailable': 'Results not captured',
}
const SHORT_REASONS: Record<string, string> = {
  'Does not meet the Lazy CWL participation rule': '',
  'Below the minimum attacks': '',
  'Results are not complete': '',
  'Missed CWL sync': 'Missed sync',
  'Lingering in hosting clan': 'Lingering',
  'Left the family': 'Left family',
  'Received a bonus in one of the previous three CWL months': 'Bonus in last 3 seasons',
  'Already selected for a bonus this CWL month': 'Already selected',
  'Already selected for a bonus this season': 'Already selected',
}
const reasonParts = (account: RaffleAccount) =>
  (account.exclusion || '').split('; ').map(part => part.trim()).filter(Boolean)

/** Player-specific reasons only; the outcome chip already says Below rule. */
export function playerReasons(account: RaffleAccount): string[] {
  return [...new Set(reasonParts(account)
    .filter(part => !(part in CLAN_WIDE_REASONS))
    .map(part => part in SHORT_REASONS ? SHORT_REASONS[part] : part)
    .filter(Boolean))]
}

/** Clan-wide reasons shared by every listed account. */
export function clanWideReasons(accounts: RaffleAccount[]): string[] {
  if (!accounts.length) return []
  return Object.keys(CLAN_WIDE_REASONS)
    .filter(reason => accounts.every(account => reasonParts(account).includes(reason)))
    .map(reason => CLAN_WIDE_REASONS[reason])
}

export type BonusReviewGuard = {
  canManage: boolean;
  archived: boolean;
  policyDirty: boolean;
  roleDirty: boolean;
  reviewDirty: boolean;
  candidateOpen: boolean;
  countReady: boolean;
  needsMinimum: boolean;
  rolesUnavailable: boolean;
  resultsMissing: boolean;
}
export type BonusReviewBlocker =
  | 'access' | 'archived' | 'minimum-dirty' | 'role-dirty' | 'open-review'
  | 'count' | 'minimum' | 'roles' | 'results'

export type BonusReviewLine = { id: BonusReviewBlocker; text: string; blocks: boolean }

/**
 * The one source for the lines under Review eligibility. Only `blocks` lines
 * disable the button (today's conditions); the others show the fix only.
 */
export function bonusReviewBlockers(guard: BonusReviewGuard): BonusReviewLine[] {
  const lines: [boolean, BonusReviewBlocker, string, boolean][] = [
    [!guard.canManage, 'access', 'Bonus access needed', true],
    [guard.archived, 'archived', 'Archived season · read only', true],
    [guard.policyDirty, 'minimum-dirty', 'Save the minimum', true],
    [guard.roleDirty, 'role-dirty', 'Save the representative role', true],
    [guard.reviewDirty || guard.candidateOpen, 'open-review', 'Save the open review', true],
    [!guard.countReady, 'count', 'Enter the bonus count', true],
    [guard.needsMinimum, 'minimum', 'Set the Main minimum', true],
    [guard.rolesUnavailable, 'roles', 'Discord roles unavailable · Retry', false],
    [guard.resultsMissing, 'results', 'Results not captured', false],
  ]
  return lines.filter(([active]) => active).map(([, id, text, blocks]) => ({ id, text, blocks }))
}

export function reviewBlocked(lines: BonusReviewLine[]): boolean {
  return lines.some(line => line.blocks)
}

export type BonusListMode = 'candidates' | 'eligible' | 'excluded' | 'winners'

export function bonusCandidateStatus(account: RaffleAccount, mode: BonusListMode): string {
  if (mode === 'winners') return ''
  if (account.exclusion) return account.exclusion
  if (mode === 'excluded') return 'Not included'
  if (account.bonus_review?.override_reason) return 'Included by staff exception'
  if (mode === 'eligible') return ''
  if (account.three_cycle_cooldown) return 'Got a bonus in the last 3 seasons · cannot enter this season'
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
