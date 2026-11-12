import type { Pool } from "./api";
import type { BonusAccount, BonusClan, BonusData } from "./bonus";
import type { BonusStep } from "./bonusStatus";

export type BonusReview = {
  flags: string[];
  override_reason: string;
  revision?: number;
  updated_by?: string | null;
  updated_at?: string | null;
};

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
  prior_winner_cycle?: string | null;
  prior_winner_label?: string | null;
  eligible_again?: string | null;
  sit_out_months?: number;
  sit_out_excluded?: boolean;
  is_representative?: boolean;
  representative_status?: string;
};
export type BonusAllowance = {
  status: "ready" | "pending" | "unavailable";
  total: number | null;
  base: number | null;
  wins: number;
  completed_wars: number;
  rounds: number | null;
  league: string | null;
  team_size: number | null;
  reason: string;
  rules_version: string;
};
export type RafflePreview = {
  allowance_source?: "automatic" | "staff";
  allowance?: BonusAllowance | null;
  cycle: string;
  pool: Pool;
  clan_tag: string;
  clan_name: string;
  minimum: number | null;
  qualification_rule?: string | null;
  rules_version?: number;
  slots: number;
  available: number;
  confirmed: number;
  eligible: RaffleAccount[];
  excluded: RaffleAccount[];
  blocking_reasons: string[];
  fingerprint: string;
};
export type SavedDraw = {
  id: number;
  pool: Pool;
  clan_tag: string;
  cycle: string;
  created_at: string;
  approved_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  snapshot: RafflePreview & { winners: RaffleAccount[] };
  messages: string[];
  delivery: null | {
    channel_id: string;
    status: string;
    failure: string | null;
    pages: { page: number; status: string; message_id: string | null }[];
  };
};
/** One family-wide FWA Rep account: 2 chances in Lazy draws. */
export type RepAccount = {
  tag: string;
  player_name: string;
  town_hall: number | null;
  user_id: string | null;
  note: string;
  revision: number;
};
export type RaffleData = Omit<BonusData, "accounts"> & {
  season_status: string;
  historical_accounts_count: number;
  sync: {
    enabled: boolean;
    last_checked_at: string | null;
    warning: string | null;
    status?: string;
    cycle?: string | null;
  };
  roster_source: string;
  policies: Record<Pool, number | null>;
  draws: SavedDraw[];
  accounts: RaffleAccount[];
  allowances?: Record<string, BonusAllowance>;
  rep_accounts?: RepAccount[];
  bonus_reviews?: Record<string, BonusReview>;
  lazy_hosts?: BonusClan[];
  sit_out_settings?: { tag: string; name: string; months: number }[];
};
/** Card tally value: attacks over CWL rounds when known; "—" when not captured. */
export const attacksTally = (account: RaffleAccount) =>
  account.attacks === null
    ? "—"
    : `${account.attacks}${account.season_rounds ? `/${account.season_rounds}` : ""}`;

/** Reasons that apply to a whole hosting clan. They show once, above the list. */
export const CLAN_WIDE_REASONS: Record<string, string> = {
  "Hosting clan is no longer an active Lazy clan in this season":
    "Hosting clan is not an active Lazy clan this season",
  "Complete participation results are unavailable": "Results not captured",
};
const SHORT_REASONS: Record<string, string> = {
  "Does not meet the Lazy CWL participation rule": "",
  "Below the minimum attacks": "",
  "Results are not complete": "",
  "Missed CWL sync": "Missed sync",
  "Lingering in hosting clan": "Lingering",
  "Left the family": "Left family",
  "Received a Lazy bonus in one of the previous three CWL months":
    "Bonus in last 3 seasons",
  "Already selected for a bonus this CWL month": "Already selected",
  "Already selected for a bonus this season": "Already selected",
};
const reasonParts = (account: RaffleAccount) =>
  (account.exclusion || "")
    .split("; ")
    .map((part) => part.trim())
    .filter(Boolean);

/** Player-specific reasons only; the outcome chip already says Below rule. */
export function playerReasons(account: RaffleAccount): string[] {
  return [
    ...new Set(
      reasonParts(account)
        .filter(
          (part) =>
            !(part in CLAN_WIDE_REASONS) && !part.startsWith("Prior winner"),
        )
        .map((part) => (part in SHORT_REASONS ? SHORT_REASONS[part] : part))
        .filter(Boolean),
    ),
  ];
}

/** Clan-wide reasons shared by every listed account. */
export function clanWideReasons(accounts: RaffleAccount[]): string[] {
  if (!accounts.length) return [];
  return Object.keys(CLAN_WIDE_REASONS)
    .filter((reason) =>
      accounts.every((account) => reasonParts(account).includes(reason)),
    )
    .map((reason) => CLAN_WIDE_REASONS[reason]);
}

export type BonusReviewGuard = {
  canManage: boolean;
  archived: boolean;
  policyDirty: boolean;
  reviewDirty: boolean;
  candidateOpen: boolean;
  countReady: boolean;
  needsMinimum: boolean;
  /** Every player lacks results and no staff reason covers them. */
  resultsMissing: boolean;
  /** Players still without a result or a covering staff reason. */
  uncheckedCount: number;
  /** Staff can open Review for an unchecked player (Lazy, with access). */
  canReviewUnchecked: boolean;
  cycleMissing: boolean;
  hostInactive: boolean;
};
export type BonusBlockerId =
  | "access"
  | "archived"
  | "minimum-dirty"
  | "open-review"
  | "count"
  | "minimum"
  | "results"
  | "partial"
  | "cycle"
  | "inactive";

export type BonusBlockerLine = {
  id: BonusBlockerId;
  text: string;
  /** A blocking line disables the action it guards. */
  blocks: boolean;
  /** The step bar shows this line as the step's red reason. */
  bar: boolean;
};

/**
 * The one source of blockers. The step bar, the lines in each panel and every
 * disabled action read this; nothing else decides.
 */
export function bonusStepBlockers(
  guard: BonusReviewGuard,
): Record<BonusStep, BonusBlockerLine[]> {
  const line = (
    active: boolean,
    id: BonusBlockerId,
    text: string,
    blocks: boolean,
    bar = blocks,
  ): [boolean, BonusBlockerLine] => [active, { id, text, blocks, bar }];
  const pick = (lines: [boolean, BonusBlockerLine][]) =>
    lines.filter(([active]) => active).map(([, item]) => item);
  const access = line(!guard.canManage, "access", "Bonus access needed", true);
  const archived = line(
    guard.archived,
    "archived",
    "Archived season · read only",
    true,
  );
  const minimumDirty = line(
    guard.policyDirty,
    "minimum-dirty",
    "Save the minimum",
    true,
  );
  const openReview = line(
    guard.reviewDirty || guard.candidateOpen,
    "open-review",
    "Save the open review",
    true,
  );
  const draw = pick([access, archived, minimumDirty, openReview]);
  return {
    results: pick([
      line(guard.cycleMissing, "cycle", "CWL month not set", false, true),
      line(
        guard.resultsMissing,
        "results",
        "Results not captured",
        false,
        true,
      ),
      line(
        !guard.resultsMissing && guard.uncheckedCount > 0,
        "partial",
        `${guard.uncheckedCount} not checked${guard.canReviewUnchecked ? " · Review" : ""}`,
        false,
        true,
      ),
    ]),
    rules: pick([
      access,
      archived,
      minimumDirty,
      openReview,
      line(!guard.countReady, "count", "Enter the bonus count", true),
      line(
        guard.needsMinimum && !guard.policyDirty,
        "minimum",
        "Set the Main minimum",
        true,
      ),
      line(
        guard.hostInactive,
        "inactive",
        "Hosting clan is not an active Lazy clan this season",
        false,
        true,
      ),
    ]),
    draw,
    approve: pick([access, archived]),
    announce: pick([archived]),
  };
}

export function reviewBlocked(lines: BonusBlockerLine[]): boolean {
  return lines.some((line) => line.blocks);
}

export type BonusListMode = "candidates" | "eligible" | "excluded" | "winners";

export function bonusCandidateStatus(
  account: RaffleAccount,
  mode: BonusListMode,
): string {
  if (mode === "winners") return "";
  if (account.exclusion) return account.exclusion;
  if (mode === "excluded") return "Not included";
  if (account.bonus_review?.override_reason)
    return "Included by staff exception";
  if (mode === "eligible") return "";
  if (account.sit_out_excluded && account.prior_winner_label)
    return `Prior winner (${account.prior_winner_label})`;
  return account.manual_candidate ? "Added by staff · review eligibility" : "";
}

export type BonusDrawGuard = {
  canManage: boolean;
  busy: boolean;
  archived: boolean;
  policyDirty: boolean;
  reviewDirty: boolean;
  reviewOpen: boolean;
  candidateOpen: boolean;
  lookingUp: boolean;
  blocked: boolean;
};

export function canSaveBonusDraw(guard: BonusDrawGuard): boolean {
  return (
    guard.canManage &&
    !guard.busy &&
    !guard.archived &&
    !guard.policyDirty &&
    !guard.reviewDirty &&
    !guard.reviewOpen &&
    !guard.candidateOpen &&
    !guard.lookingUp &&
    !guard.blocked
  );
}
