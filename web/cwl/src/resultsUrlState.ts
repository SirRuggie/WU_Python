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
  "open",
] as const;
export type ResultsSort = "name" | "attacks-desc" | "stars-desc";
export type ResultsUrlState = {
  pool?: Pool;
  clan?: string;
  outcome?: OutcomeFilter;
  sort?: ResultsSort;
  step?: BonusStep;
  /** Steps view with the step not known yet (`open=steps`); the steps page replaces it with a step. The key is not `view`, which names the dashboard page. */
  view?: "steps";
};
const outcomes = [
  "all",
  "meets",
  "below",
  "partial",
  "not_checked",
  "did_not_join",
  "filler",
  "not_assigned",
];
const sorts = ["name", "attacks-desc", "stars-desc"];
const steps = ["results", "rules", "draw", "approve", "announce"];
/** Links saved before the step names changed keep working. */
const legacySteps: Record<string, string> = {
  eligibility: "rules",
  approval: "approve",
  announcement: "announce",
};

export function parseResultsState(query: string): ResultsUrlState {
  const params = new URLSearchParams(query);
  const value = (key: string, allowed: string[]) =>
    allowed.includes(params.get(key) || "") ? params.get(key)! : undefined;
  const clan = params.get("clan") || "";
  const step = value("step", [...steps, ...Object.keys(legacySteps)]);
  return {
    pool: value("pool", ["main", "lazy"]) as Pool | undefined,
    clan: /^#[0289PYLQGRJCUV]{3,15}$/.test(clan) ? clan : undefined,
    outcome: value("outcome", outcomes) as OutcomeFilter | undefined,
    sort: value("sort", sorts) as ResultsSort | undefined,
    step: (step && (legacySteps[step] || step)) as BonusStep | undefined,
    view: params.get("open") === "steps" ? "steps" : undefined,
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
  else if (state.view) params.set("open", state.view);
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
