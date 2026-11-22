import { api, type Season } from "./api";
import { loadBonusStatus, bonusStepStates } from "./bonusStatus";
import type { PublicationDraft } from "./publication";
import { seasonMonth } from "./seasonLabels";

/** A missing referenced season is unavailable; only explicit NULL may fall back. */
export function lifecycleSeason(seasons: Season[], id: number | null) {
  if (id !== null) return seasons.find((season) => season.id === id);
  return [...seasons]
    .filter(
      (season) =>
        !season.history_only &&
        season.status !== "archived" &&
        seasonMonth(season),
    )
    .sort(
      (a, b) => seasonMonth(b).localeCompare(seasonMonth(a)) || b.id - a.id,
    )[0];
}
export type LifecycleReadiness = { published: boolean; blockers: string[] };
/** Existing publication and bonus readers only; missing/error is never completion. */
export async function loadLifecycleReadiness(
  id: number,
): Promise<LifecycleReadiness> {
  const [publication, bonus] = await Promise.all([
    api<PublicationDraft>(`/seasons/${id}/publication`),
    loadBonusStatus(String(id)),
  ]);
  if (
    !publication ||
    !Array.isArray(publication.preview?.accounts) ||
    bonus.season_id !== id
  )
    throw new Error(
      "Season status unavailable. Refresh before starting next month.",
    );
  const pools = new Set(publication.preview.accounts.map((row) => row.pool));
  const published =
    typeof publication.published?.version === "number" &&
    publication.published.version > 0;
  const blockers: string[] = [];
  for (const pool of pools) {
    const clans = bonus.pools[pool];
    if (!Array.isArray(clans) || !clans.length) {
      blockers.push(
        `${pool === "main" ? "Main" : "Lazy"} results and bonuses unavailable`,
      );
      continue;
    }
    for (const clan of clans) {
      const steps = bonusStepStates(clan, pool, bonus.main_minimum);
      if (steps.find((step) => step.id === "results")?.state !== "done")
        blockers.push(`${clan.name}: results`);
      if (steps.find((step) => step.id === "announce")?.state !== "done")
        blockers.push(`${clan.name}: bonuses`);
    }
  }
  return { published, blockers };
}

/** Current flags cannot reconstruct old signup transitions. Never invent history. */
export function lifecycleStepStates(
  season: Season,
  shown: boolean,
  published: boolean,
) {
  const current =
    season.status === "archived"
      ? 4
      : !shown
        ? 0
        : published
          ? 3
          : season.signup_open
            ? 1
            : 2;
  const known = [
    shown,
    shown && season.signup_open,
    !season.signup_open || season.status === "archived",
    published,
    season.status === "archived",
  ];
  return [
    "Shown to members",
    "Signups open",
    "Signups closed",
    "Published",
    "Locked",
  ].map((label, index) => ({
    label,
    state:
      index === current
        ? "Current"
        : known[index]
          ? "Done"
          : index < current
            ? "Not recorded"
            : "Not reached",
  }));
}
