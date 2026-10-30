import type { Pool } from "./api";
import type { RosterAccount, RosterClan } from "./roster";
import { rosterMemberKey } from "./rosterGrouping";

export const ROSTER_RELEASE_STATUSES = [
  "assigned",
  "unassigned",
  "missing_weight",
  "over_capacity",
  "locked",
] as const;
export type RosterReleaseStatus = (typeof ROSTER_RELEASE_STATUSES)[number];
export const ROSTER_RELEASE_SORTS = [
  "unassigned_first",
  "weight_desc",
  "weight_asc",
  "name",
  "town_hall_desc",
  "town_hall_asc",
  "assigned_clan",
  "signed_up_desc",
  "signed_up_asc",
] as const;
export type RosterReleaseSort = (typeof ROSTER_RELEASE_SORTS)[number];

export type RosterReleaseFilters = {
  search: string;
  pool: Pool | "all";
  statuses: RosterReleaseStatus[];
  minWeight: number | null;
  maxWeight: number | null;
  townHalls: number[];
  assignedClanTags: string[];
};
export type RosterReleasePreferences = RosterReleaseFilters & {
  sort: RosterReleaseSort;
  grouped: boolean;
};
export const DEFAULT_ROSTER_RELEASE_PREFERENCES: RosterReleasePreferences = {
  search: "",
  pool: "all",
  statuses: [],
  minWeight: null,
  maxWeight: null,
  townHalls: [],
  assignedClanTags: [],
  sort: "unassigned_first",
  grouped: false,
};
export type RosterReleaseFacets = {
  status: Record<RosterReleaseStatus, number>;
  townHall: Record<string, number>;
  assignedClan: Record<string, number>;
  pool: Record<Pool, number>;
  weightRangeCount: number;
};

const statusSet = new Set<string>(ROSTER_RELEASE_STATUSES);
const sortSet = new Set<string>(ROSTER_RELEASE_SORTS);
const localeCompare = (left: string, right: string) =>
  left.localeCompare(right, undefined, { sensitivity: "base" });
const unique = <T>(values: T[]) => [...new Set(values)];

/** Parse untrusted localStorage JSON field by field; unknown versions are harmless. */
export function parseRosterReleasePreferences(
  raw: unknown,
): RosterReleasePreferences {
  let input: unknown = raw;
  if (typeof raw === "string") {
    try {
      input = JSON.parse(raw);
    } catch {
      input = null;
    }
  }
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return {
      ...DEFAULT_ROSTER_RELEASE_PREFERENCES,
      statuses: [],
      townHalls: [],
      assignedClanTags: [],
    };
  }
  const value = input as Record<string, unknown>;
  const strings = (candidate: unknown, allowed?: Set<string>) =>
    Array.isArray(candidate)
      ? unique(
          candidate.filter(
            (item): item is string =>
              typeof item === "string" &&
              item.length <= 120 &&
              (!allowed || allowed.has(item)),
          ),
        )
      : [];
  const weight = (candidate: unknown) =>
    typeof candidate === "number" &&
    Number.isSafeInteger(candidate) &&
    candidate >= 0
      ? candidate
      : null;
  const minWeight = weight(value.minWeight);
  const maxWeight = weight(value.maxWeight);
  return {
    search: typeof value.search === "string" ? value.search.slice(0, 200) : "",
    pool: value.pool === "main" || value.pool === "lazy" ? value.pool : "all",
    statuses: strings(value.statuses, statusSet) as RosterReleaseStatus[],
    minWeight:
      minWeight !== null && maxWeight !== null && minWeight > maxWeight
        ? null
        : minWeight,
    maxWeight:
      minWeight !== null && maxWeight !== null && minWeight > maxWeight
        ? null
        : maxWeight,
    townHalls: Array.isArray(value.townHalls)
      ? unique(
          value.townHalls.filter(
            (item): item is number =>
              typeof item === "number" &&
              Number.isInteger(item) &&
              item >= 1 &&
              item <= 30,
          ),
        )
      : [],
    assignedClanTags: strings(value.assignedClanTags).filter((tag) =>
      tag.startsWith("#"),
    ),
    sort:
      typeof value.sort === "string" && sortSet.has(value.sort)
        ? (value.sort as RosterReleaseSort)
        : "unassigned_first",
    grouped: value.grouped === true,
  };
}
export function serializeRosterReleasePreferences(
  preferences: RosterReleasePreferences,
): string {
  return JSON.stringify(parseRosterReleasePreferences(preferences));
}

function statusFlags(
  account: RosterAccount,
  overCapacity: Set<string>,
): Record<RosterReleaseStatus, boolean> {
  return {
    assigned: !!account.assigned_clan_tag,
    unassigned: !account.assigned_clan_tag,
    missing_weight: account.effective_weight === null,
    over_capacity:
      !!account.assigned_clan_tag &&
      overCapacity.has(account.assigned_clan_tag),
    locked: account.kept,
  };
}

/** Capacity is calculated from the full working roster, not the currently filtered rows. */
function overCapacityClans(
  accounts: RosterAccount[],
  clans: RosterClan[],
): Set<string> {
  const assigned = new Map<string, number>();
  for (const account of accounts) {
    if (account.assigned_clan_tag) {
      assigned.set(
        account.assigned_clan_tag,
        (assigned.get(account.assigned_clan_tag) || 0) + 1,
      );
    }
  }
  return new Set(
    clans
      .filter((clan) => (assigned.get(clan.tag) || 0) > clan.effective_capacity)
      .map((clan) => clan.tag),
  );
}

type Section = "status" | "townHall" | "assignedClan" | "pool" | "weightRange";
function matches(
  account: RosterAccount,
  filters: RosterReleaseFilters,
  overCapacity: Set<string>,
  omit?: Section,
): boolean {
  const term = filters.search.trim().toLocaleLowerCase();
  if (
    term &&
    ![account.player_name, account.tag, account.user_id].some((value) =>
      value.toLocaleLowerCase().includes(term),
    )
  )
    return false;
  if (
    omit !== "pool" &&
    filters.pool !== "all" &&
    account.pool !== filters.pool
  )
    return false;
  if (
    omit !== "status" &&
    filters.statuses.length &&
    !filters.statuses.some(
      (status) => statusFlags(account, overCapacity)[status],
    )
  )
    return false;
  if (
    omit !== "townHall" &&
    filters.townHalls.length &&
    (account.town_hall === null ||
      !filters.townHalls.includes(account.town_hall))
  )
    return false;
  if (
    omit !== "assignedClan" &&
    filters.assignedClanTags.length &&
    (!account.assigned_clan_tag ||
      !filters.assignedClanTags.includes(account.assigned_clan_tag))
  )
    return false;
  if (
    omit !== "weightRange" &&
    (filters.minWeight !== null || filters.maxWeight !== null)
  ) {
    const weight = account.effective_weight;
    if (
      weight === null ||
      (filters.minWeight !== null && weight < filters.minWeight) ||
      (filters.maxWeight !== null && weight > filters.maxWeight)
    )
      return false;
  }
  return true;
}

/** Each facet ignores only its own section, so its counts stay useful while selected. */
export function deriveRosterRelease(
  accounts: RosterAccount[],
  clans: RosterClan[],
  filters: RosterReleaseFilters,
) {
  const full = overCapacityClans(accounts, clans);
  const facets: RosterReleaseFacets = {
    status: {
      assigned: 0,
      unassigned: 0,
      missing_weight: 0,
      over_capacity: 0,
      locked: 0,
    },
    townHall: {},
    assignedClan: {},
    pool: { main: 0, lazy: 0 },
    weightRangeCount: 0,
  };
  for (const account of accounts) {
    if (matches(account, filters, full, "status")) {
      const flags = statusFlags(account, full);
      for (const status of ROSTER_RELEASE_STATUSES)
        if (flags[status]) facets.status[status]++;
    }
    if (matches(account, filters, full, "townHall")) {
      const key =
        account.town_hall === null ? "unknown" : String(account.town_hall);
      facets.townHall[key] = (facets.townHall[key] || 0) + 1;
    }
    if (matches(account, filters, full, "assignedClan")) {
      const key = account.assigned_clan_tag || "unassigned";
      facets.assignedClan[key] = (facets.assignedClan[key] || 0) + 1;
    }
    if (matches(account, filters, full, "pool")) facets.pool[account.pool]++;
    if (matches(account, filters, full, "weightRange"))
      facets.weightRangeCount++;
  }
  return {
    matches: accounts.filter((account) => matches(account, filters, full)),
    facets,
    globalMissingWeightCount: accounts.filter(
      (account) => account.effective_weight === null,
    ).length,
  };
}

function nullableNumber(
  left: number | null,
  right: number | null,
  direction: 1 | -1,
): number {
  if (left === null) return right === null ? 0 : 1;
  if (right === null) return -1;
  return (left - right) * direction;
}
function signupTime(account: RosterAccount): number | null {
  if (!account.signed_up_at) return null;
  const value = Date.parse(account.signed_up_at);
  return Number.isFinite(value) ? value : null;
}
function compareAccounts(
  left: RosterAccount,
  right: RosterAccount,
  sort: RosterReleaseSort,
): number {
  let comparison = 0;
  switch (sort) {
    case "unassigned_first":
      comparison =
        Number(!!left.assigned_clan_tag) - Number(!!right.assigned_clan_tag) ||
        nullableNumber(left.effective_weight, right.effective_weight, -1);
      break;
    case "weight_desc":
      comparison = nullableNumber(
        left.effective_weight,
        right.effective_weight,
        -1,
      );
      break;
    case "weight_asc":
      comparison = nullableNumber(
        left.effective_weight,
        right.effective_weight,
        1,
      );
      break;
    case "town_hall_desc":
      comparison = nullableNumber(left.town_hall, right.town_hall, -1);
      break;
    case "town_hall_asc":
      comparison = nullableNumber(left.town_hall, right.town_hall, 1);
      break;
    case "assigned_clan":
      comparison =
        left.assigned_clan_tag === null
          ? right.assigned_clan_tag === null
            ? 0
            : 1
          : right.assigned_clan_tag === null
            ? -1
            : localeCompare(left.assigned_clan_tag, right.assigned_clan_tag);
      break;
    case "signed_up_desc":
      comparison = nullableNumber(signupTime(left), signupTime(right), -1);
      break;
    case "signed_up_asc":
      comparison = nullableNumber(signupTime(left), signupTime(right), 1);
      break;
    case "name":
      break;
  }
  return (
    comparison ||
    localeCompare(left.player_name, right.player_name) ||
    localeCompare(left.tag, right.tag)
  );
}

/** In grouped mode the first sorted account positions each member; its rows remain sorted. */
export function orderRosterReleaseAccounts(
  accounts: RosterAccount[],
  sort: RosterReleaseSort,
  grouped = false,
): RosterAccount[] {
  const ordered = [...accounts].sort((left, right) =>
    compareAccounts(left, right, sort),
  );
  if (!grouped) return ordered;
  const groups = new Map<string, RosterAccount[]>();
  for (const account of ordered) {
    const key = rosterMemberKey(account);
    const group = groups.get(key) || [];
    group.push(account);
    groups.set(key, group);
  }
  return [...groups.values()].flat();
}

/** Show at least the requested count; never split a Discord member group. */
export function progressiveRosterReleaseAccounts(
  ordered: RosterAccount[],
  requestedCount = 50,
  grouped = false,
) {
  const count = Number.isFinite(requestedCount)
    ? Math.max(0, Math.floor(requestedCount))
    : 50;
  if (!grouped) {
    const visible = ordered.slice(0, count);
    return {
      visible,
      hasMore: visible.length < ordered.length,
      nextCount: visible.length + 50,
    };
  }
  const visible: RosterAccount[] = [];
  for (let index = 0; index < ordered.length; ) {
    if (visible.length >= count && visible.length > 0) break;
    const key = rosterMemberKey(ordered[index]);
    do {
      visible.push(ordered[index++]);
    } while (index < ordered.length && rosterMemberKey(ordered[index]) === key);
  }
  return {
    visible,
    hasMore: visible.length < ordered.length,
    nextCount: visible.length + 50,
  };
}

export function reconcileRosterSelection(
  selectedTags: string[],
  allAccounts: RosterAccount[],
): string[] {
  const existing = new Set(allAccounts.map((account) => account.tag));
  return unique(selectedTags.filter((tag) => existing.has(tag)));
}
export const MAX_ROSTER_SELECTION = 50;

/** Quick picks follow the entire filtered order, including rows not rendered yet. */
export function quickSelectRosterMatches(
  matches: RosterAccount[],
  count: 15 | 30,
) {
  return matches
    .filter((account) => !account.kept)
    .slice(0, count)
    .map((account) => account.tag);
}

/** All retains matching selections and any hidden selections, subject to the cap. */
export function addAllRosterMatches(
  selectedTags: string[],
  matches: RosterAccount[],
) {
  const next = unique([...selectedTags, ...matches.map((account) => account.tag)]);
  return next.length <= MAX_ROSTER_SELECTION ? next : null;
}

export function toggleRosterSelection(selectedTags: string[], tag: string) {
  if (selectedTags.includes(tag))
    return selectedTags.filter((item) => item !== tag);
  return selectedTags.length < MAX_ROSTER_SELECTION
    ? [...selectedTags, tag]
    : null;
}
export function rosterSelectionSummary(
  selectedTags: string[],
  allAccounts: RosterAccount[],
  matches: RosterAccount[],
  visible: RosterAccount[],
) {
  const selected = reconcileRosterSelection(selectedTags, allAccounts);
  const matching = new Set(matches.map((account) => account.tag));
  const shown = new Set(visible.map((account) => account.tag));
  return {
    selectedCount: selected.length,
    matchingSelectedCount: selected.filter((tag) => matching.has(tag)).length,
    hiddenSelectedCount: selected.filter((tag) => !shown.has(tag)).length,
    outsideFilterSelectedCount: selected.filter((tag) => !matching.has(tag))
      .length,
    staleSelectedCount: unique(selectedTags).length - selected.length,
    allMatchesSelected:
      matches.length > 0 &&
      matches.every((account) => selected.includes(account.tag)),
  };
}
