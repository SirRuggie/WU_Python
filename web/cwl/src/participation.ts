import type { Pool } from "./api";

export type ParticipationDisplayStatus = {
  code: string;
  label: string;
  warning: string | null;
  failed_clan: boolean;
  round: number | null;
  last_check_failed?: boolean;
};
type StatusAccount = {
  source_status?: string;
  display_status?: ParticipationDisplayStatus;
  assigned_clan_tag?: string | null;
  assigned_clan_name?: string | null;
};

export type ParticipationAccount = {
  roster_token?: string;
  prior_winner_cycle?: string | null;
  eligible_again?: string | null;
  sit_out_excluded?: boolean;
  previous_results?: {
    pool: string;
    assigned_clan_name: string | null;
    assigned_clan_tag: string | null;
    attacks: number | null;
    stars: number | null;
  };
  tag: string;
  user_id?: string | null;
  player_name: string;
  town_hall: number | null;
  pool: Pool;
  assigned_clan_tag: string | null;
  assigned_clan_name: string | null;
  attacks: number | null;
  stars: number | null;
  notes: string;
  revision: number;
  updated_by: string | null;
  updated_at: string | null;
  in_latest_publication: boolean;
  recorded_publication_version?: number | null;
  roster_changed?: boolean;
  source_attacks?: number | null;
  source_stars?: number | null;
  source_status?: string;
  display_status?: ParticipationDisplayStatus;
  source_checked_at?: string | null;
  source_complete?: boolean;
  /** Finished CWL with no league-group or war roster entry. */
  did_not_join?: boolean;
  /** Staff marked this account as a roster filler. */
  roster_filler?: boolean;
  attacks_override?: boolean;
  stars_override?: boolean;
  source_warning?: string | null;
  attacks_origin?: "source" | "manual" | "unknown";
  stars_origin?: "source" | "manual" | "unknown";
};
export type ParticipationSync = {
  cycle: string | null;
  cycle_source: "settings" | "manage_binding" | "none";
  enabled: boolean;
  status: string;
  last_checked_at: string | null;
  last_success_at: string | null;
  updated_at: string | null;
  warning: string | null;
};
export type ParticipationData = {
  scope_counts?: { current_signups: number; saved_history: number };
  historical_accounts_count?: number;
  roster_source?: string;
  publication_version: number | null;
  accounts: ParticipationAccount[];
  sync?: ParticipationSync;
};

export function participationStatus(
  account: StatusAccount,
): ParticipationDisplayStatus {
  return (
    account.display_status || {
      code: account.source_status || "never",
      label: syncStatusLabel(account.source_status),
      warning: null,
      failed_clan: false,
      round: null,
    }
  );
}

/** Summarize only the supplied displayed scope, before pagination. */
export function participationSummary(
  accounts: StatusAccount[],
  sync?: { status?: string; cycle?: string | null; warning?: string | null },
) {
  if (sync?.status === "season_mismatch") {
    return {
      label: "CWL month mismatch",
      warning:
        sync.warning || "Clash CWL month differs from the selected month",
      affected: 0,
      count: accounts.length,
      updated: 0,
    };
  }
  const statuses = accounts.map(participationStatus);
  // Did not join and unassigned accounts are final; they never make CWL incomplete.
  const settled = statuses.filter(
    (status) => !["did_not_join", "unassigned"].includes(status.code),
  );
  const failed = accounts.filter(
    (account) => participationStatus(account).failed_clan,
  );
  const clans = [
    ...new Map(
      failed.map((account) => [
        account.assigned_clan_tag,
        account.assigned_clan_name ||
          account.assigned_clan_tag ||
          "Unknown clan",
      ]),
    ).values(),
  ];
  const round = Math.max(0, ...statuses.map((status) => status.round || 0));
  const active = statuses.some((status) => status.code === "in_progress");
  const updated = statuses.filter((status) =>
    ["in_progress", "complete", "preparation"].includes(status.code),
  ).length;
  const label = active
    ? `CWL in progress${round ? ` · round ${round} of 7` : ""}`
    : settled.length && settled.every((status) => status.code === "complete")
      ? "CWL complete"
      : statuses.find((status) => status.warning)?.label ||
        (sync?.status === "waiting"
          ? syncStatusLabel("waiting", sync.cycle)
          : statuses[0]?.label || "No accounts in this view");
  const otherWarnings = [
    ...new Set(
      statuses
        .filter((status) => !status.failed_clan)
        .map((status) => status.warning)
        .filter((warning): warning is string => !!warning),
    ),
  ];
  const saved = failed.filter(
    (account) => participationStatus(account).code === "stale",
  ).length;
  const withoutSaved = failed.length - saved;
  const failureDetails = [
    saved
      ? `Showing last saved results for ${saved} account${saved === 1 ? "" : "s"} in this view.`
      : "",
    withoutSaved
      ? `No saved results yet for ${withoutSaved} account${withoutSaved === 1 ? "" : "s"} in this view.`
      : "",
  ]
    .filter(Boolean)
    .join(" ");
  // The adapter keeps this per-clan fact after fresh row warnings expire. A
  // season-wide sync warning alone must never accuse a filtered-out clan.
  const previousFailure = statuses.some((status) => status.last_check_failed)
    ? sync?.warning
    : null;
  const warning = clans.length
    ? `${clans.length} clan${clans.length === 1 ? "" : "s"} could not refresh: ${clans.join(", ")}. ${failureDetails}`
    : [...new Set([...otherWarnings, previousFailure].filter(Boolean))].join(
        " ",
      );
  return {
    label,
    warning,
    affected: failed.length,
    count: accounts.length,
    updated,
  };
}
export type ParticipationSort =
  | "name"
  | "attacks-asc"
  | "attacks-desc"
  | "stars-asc"
  | "stars-desc"
  | "th-asc"
  | "th-desc";
export type ParticipationFilters = {
  search: string;
  pool: Pool | "all";
  clan: string;
  sort: ParticipationSort;
};

export function visibleParticipation(
  accounts: ParticipationAccount[],
  filters: ParticipationFilters,
): ParticipationAccount[] {
  const query = filters.search.trim().toLocaleLowerCase();
  const filtered = accounts.filter(
    (account) =>
      (filters.pool === "all" || account.pool === filters.pool) &&
      (filters.clan === "all" ||
        (account.assigned_clan_tag || "") === filters.clan) &&
      (!query ||
        [
          account.player_name,
          account.tag,
          account.assigned_clan_name || "",
          account.assigned_clan_tag || "",
        ].some((value) => value.toLocaleLowerCase().includes(query))),
  );
  const field = filters.sort.startsWith("attacks")
    ? "attacks"
    : filters.sort.startsWith("stars")
      ? "stars"
      : filters.sort.startsWith("th")
        ? "town_hall"
        : null;
  const direction = filters.sort.endsWith("desc") ? -1 : 1;
  return filtered.sort((left, right) => {
    if (field) {
      const a = left[field],
        b = right[field];
      if (a === null && b !== null) return 1;
      if (b === null && a !== null) return -1;
      if (a !== null && b !== null && a !== b) return (a - b) * direction;
    }
    return (
      left.player_name.localeCompare(right.player_name) ||
      left.tag.localeCompare(right.tag)
    );
  });
}

export function canUseSyncedResults(account: ParticipationAccount): boolean {
  return (
    !!(
      account.attacks_override ||
      account.stars_override ||
      account.roster_changed
    ) &&
    ((account.source_attacks !== null &&
      account.source_attacks !== undefined) ||
      (account.source_stars !== null && account.source_stars !== undefined))
  );
}
export function validCwlCycle(value: string): boolean {
  return /^20\d{2}-(0[1-9]|1[0-2])$/.test(value);
}

export function syncStatusLabel(
  value: string | null | undefined,
  cycle?: string | null,
): string {
  if (value === "waiting") {
    if (!cycle || !validCwlCycle(cycle)) return "Waiting for Clash CWL";
    const month = new Date(`${cycle}-01T00:00:00Z`).toLocaleString("en-US", {
      month: "long",
      timeZone: "UTC",
    });
    return `${month} CWL has not started in Clash yet`;
  }
  const labels: Record<string, string> = {
    never: "Not checked",
    complete: "Complete",
    partial: "Partial",
    preparation: "War preparation",
    stale: "Stale",
    unavailable: "Unavailable",
    unassigned: "No assigned clans",
    season_mismatch: "CWL month mismatch",
    no_data: "No CWL data",
    missing: "Not checked",
    historical: "Historical",
  };
  return labels[value || ""] || value || "Not configured";
}
