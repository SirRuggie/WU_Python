import type { Pool } from "./api";
import type { BonusStep } from "./bonusStatus";
import type { OutcomeFilter } from "./participationOutcome";

/** Results and Bonus medals keep pool, clan, outcome, sort and step in the URL. */
export const resultsStateKeys = [
  "pool",
  "clan",
  "outcome",
  "sort",
  "step",
] as const;
export type ResultsSort = "name" | "attacks-desc" | "stars-desc";
export type ResultsUrlState = {
  pool?: Pool;
  clan?: string;
  outcome?: OutcomeFilter;
  sort?: ResultsSort;
  step?: BonusStep;
};
const outcomes = ["all", "meets", "below", "not_checked"];
const sorts = ["name", "attacks-desc", "stars-desc"];
const steps = ["results", "eligibility", "draw", "approval", "announcement"];

export function parseResultsState(query: string): ResultsUrlState {
  const params = new URLSearchParams(query);
  const value = (key: string, allowed: string[]) =>
    allowed.includes(params.get(key) || "") ? params.get(key)! : undefined;
  const clan = params.get("clan") || "";
  return {
    pool: value("pool", ["main", "lazy"]) as Pool | undefined,
    clan: /^#[0289PYLQGRJCUV]{3,15}$/.test(clan) ? clan : undefined,
    outcome: value("outcome", outcomes) as OutcomeFilter | undefined,
    sort: value("sort", sorts) as ResultsSort | undefined,
    step: value("step", steps) as BonusStep | undefined,
  };
}

/** Defaults stay out of the URL so plain links keep their short form. */
export function resultsStateQuery(state: ResultsUrlState): string {
  const params = new URLSearchParams();
  if (state.pool) params.set("pool", state.pool);
  if (state.clan) params.set("clan", state.clan);
  if (state.outcome && state.outcome !== "all")
    params.set("outcome", state.outcome);
  if (state.sort && state.sort !== "name") params.set("sort", state.sort);
  if (state.step) params.set("step", state.step);
  return params.toString();
}

/** Normal selection only; modified and middle clicks open the link elsewhere. */
export function plainClick(event: {
  button: number;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}) {
  return (
    event.button === 0 &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey &&
    !event.altKey
  );
}
