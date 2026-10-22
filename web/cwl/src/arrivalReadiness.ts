export type ArrivalStatus = "arrived" | "missing" | "unknown" | "unassigned";

export type ArrivalAccount = {
  tag?: string;
  assigned_clan_tag: string | null;
  arrival_status: ArrivalStatus;
  current_clan_checked_at?: string | null;
  location_updating?: boolean;
  outside_family?: boolean;
};

const LOCATION_MAX_AGE_MS = 120_000;

/** Keep unassigned rows distinct; stale or in-flight location checks are unknown. */
export function normalizeArrivalAccount<T extends ArrivalAccount>(
  account: T,
  now: number,
): T {
  if (account.arrival_status === "unassigned") return account;

  const checkedAt = account.current_clan_checked_at
    ? Date.parse(account.current_clan_checked_at)
    : Number.NaN;
  const stale = !Number.isFinite(checkedAt) || now - checkedAt > LOCATION_MAX_AGE_MS;
  if (account.location_updating || account.arrival_status === "unknown" || stale) {
    return {
      ...account,
      arrival_status: "unknown",
      ...(account.outside_family === undefined ? {} : { outside_family: false }),
    };
  }
  return account;
}

export type ArrivalReadiness = {
  assignedCount: number;
  arrivedCount: number;
  unknownCount: number;
  ready: boolean;
};

export function summarizeArrivalReadiness<T extends ArrivalAccount>(
  accounts: readonly T[],
  options: { now: number; loading?: boolean; error?: boolean; outdated?: boolean },
): ArrivalReadiness {
  const normalized = accounts.map((account) => normalizeArrivalAccount(account, options.now));
  const assigned = normalized.filter((account) => !!account.assigned_clan_tag);
  const arrivedCount = assigned.filter((account) => account.arrival_status === "arrived").length;
  const unknownCount = assigned.filter((account) => account.arrival_status === "unknown").length;
  return {
    assignedCount: assigned.length,
    arrivedCount,
    unknownCount,
    ready:
      assigned.length >= 15 &&
      arrivedCount === assigned.length &&
      !options.loading &&
      !options.error &&
      !options.outdated,
  };
}
