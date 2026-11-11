import { lazy, useState } from "react";
import type { Season } from "./api";
import { parseResultsState } from "./resultsUrlState";

const ParticipationWorkspace = lazy(() => import("./ParticipationWorkspace"));
const BonusWorkspace = lazy(() => import("./BonusWorkspace"));

export type ResultsPageGrants = { results: boolean; bonuses: boolean };
export type ResultsPageMode = "list" | "steps";

/**
 * One page, two views. With no clan the page lists every player; with a clan it
 * shows that clan's five steps. A clan with an outcome filter is the player list
 * for that clan, so "Check these players" lands on it. Without a step in the
 * address a clan keeps the view the page is already in.
 */
export function resultsPageMode(
  urlState: string,
  previous: ResultsPageMode | null,
  grants: ResultsPageGrants,
): ResultsPageMode {
  if (!grants.bonuses) return "list";
  if (!grants.results) return "steps";
  const state = parseResultsState(urlState);
  if (!state.clan) return "list";
  if (state.step) return "steps";
  if (previous) return previous;
  return state.outcome && state.outcome !== "all" ? "list" : "steps";
}

type Props = {
  grants: ResultsPageGrants;
  seasonId: string;
  seasons: Season[];
  onSeasonChange: (id: string) => void;
  urlState: string;
  onUrlState: (state: string, push: boolean) => void;
  onDirty: (dirty: boolean) => void;
  /** Opens Strikes on one player; absent without strike add access. */
  onAddStrike?: (tag: string) => void;
};

/** Results & bonuses: `/cwl/results` and the older `/cwl/bonuses` open this page. */
export default function ResultsBonusesWorkspace({
  grants,
  urlState,
  onUrlState,
  onAddStrike,
  ...page
}: Props) {
  const [mode, setMode] = useState(() =>
    resultsPageMode(urlState, null, grants),
  );
  const [seen, setSeen] = useState(urlState);
  let current = mode;
  if (seen !== urlState) {
    current = resultsPageMode(urlState, mode, grants);
    setSeen(urlState);
    setMode(current);
  }
  const effective = resultsPageMode(urlState, current, grants);
  const open = (next: ResultsPageMode) => (query?: string) => {
    setMode(next);
    onUrlState(query ?? "", true);
  };
  return effective === "list" ? (
    <ParticipationWorkspace
      {...page}
      urlState={urlState}
      onUrlState={onUrlState}
      onAddStrike={onAddStrike}
      onBonus={grants.bonuses ? open("steps") : undefined}
    />
  ) : (
    <BonusWorkspace
      {...page}
      urlState={urlState}
      onUrlState={onUrlState}
      onResults={grants.results ? open("list") : undefined}
    />
  );
}
