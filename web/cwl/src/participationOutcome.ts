import type { Pool } from "./api";
import type { StatusTone } from "./rosterUi/primitives";

/** One CWL participation outcome, shared by Results and Bonus medals. */
export type ParticipationOutcome = "meets" | "below" | "not_checked";
export type OutcomeFilter = "all" | ParticipationOutcome;

type OutcomeAccount = {
  pool: Pool;
  attacks: number | null;
  stars: number | null;
  source_complete?: boolean;
};

export const outcomeLabels: Record<ParticipationOutcome, string> = {
  meets: "Meets rule",
  below: "Below rule",
  not_checked: "Not checked",
};

const tones: Record<ParticipationOutcome, StatusTone> = {
  meets: "success",
  below: "danger",
  not_checked: "warning",
};

/**
 * Lazy: 4+ attacks, or 3+ attacks and 8+ stars. Main: the saved minimum
 * attacks; with no saved minimum there is no outcome. Missing or partial
 * results are Not checked, as the bonus rules need complete results.
 */
export function participationOutcome(
  account: OutcomeAccount,
  mainMinimum: number | null | undefined,
): ParticipationOutcome | null {
  if (account.pool === "main" && (mainMinimum ?? null) === null) return null;
  if (account.attacks === null || account.source_complete !== true)
    return "not_checked";
  if (account.pool === "main")
    return account.attacks >= mainMinimum! ? "meets" : "below";
  if (account.stars === null) return "not_checked";
  return account.attacks >= 4 || (account.attacks >= 3 && account.stars >= 8)
    ? "meets"
    : "below";
}

export function outcomeTone(outcome: ParticipationOutcome): StatusTone {
  return tones[outcome];
}

export function outcomeCounts(
  accounts: OutcomeAccount[],
  mainMinimum: number | null | undefined,
): Record<OutcomeFilter, number> {
  const counts = { all: accounts.length, meets: 0, below: 0, not_checked: 0 };
  for (const account of accounts) {
    const outcome = participationOutcome(account, mainMinimum);
    if (outcome) counts[outcome] += 1;
  }
  return counts;
}

export function matchesOutcome(
  account: OutcomeAccount,
  filter: OutcomeFilter,
  mainMinimum: number | null | undefined,
): boolean {
  return (
    filter === "all" || participationOutcome(account, mainMinimum) === filter
  );
}

export function countText(count: number, one: string, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

const dateFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

/** The one date format on Results and Bonus medals. */
export function resultDateText(value: string) {
  return dateFormat.format(new Date(value));
}
export function resultTimeText(value: string) {
  return timeFormat.format(new Date(value));
}
