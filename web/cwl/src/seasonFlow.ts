import { api, type Season } from "./api";
export type SeasonState = {
  seasons: Season[];
  member_season: { season_id: number | null; revision: number };
};
export type SignupAction = "open" | "close" | "fix";
export function signupPlan(
  season: Season,
  state: SeasonState,
  action: SignupAction,
) {
  const hidden = state.member_season.season_id !== season.id;
  const fix = action === "fix" && season.signup_open;
  const close = action === "close";
  return {
    show: hidden && !close,
    patch: !fix,
    opened: !close,
    label: close
      ? "Close signups"
      : fix
        ? "Show to members"
        : hidden
          ? "Show and open"
          : "Open signups",
    text: close
      ? `Close Main and Lazy signups for ${season.label}? Existing signups will stay saved. The season stays visible to members.`
      : fix
        ? `Signups for ${season.label} are open, but members can't see the season. Show it to members?`
        : hidden
          ? `Members can't see ${season.label} yet. Show it to members and open signups?`
          : `Open Main and Lazy signups for ${season.label}?`,
  };
}
export async function applySignupPlan(
  season: Season,
  state: SeasonState,
  action: SignupAction,
) {
  const plan = signupPlan(season, state, action);
  let shown = false;
  if (plan.show) {
    await api("/member-season", "PUT", {
      season_id: season.id,
      revision: state.member_season.revision,
    });
    shown = true;
  }
  if (plan.patch) {
    try {
      await api(`/seasons/${season.id}`, "PATCH", {
        signup_open: plan.opened,
        expected_signup_open: !plan.opened,
      });
    } catch (error) {
      if (shown)
        throw new Error(
          `Shown to members; signups not opened: ${error instanceof Error ? error.message : "Request failed."}`,
        );
      throw error;
    }
  }
}
export function createSeasonConfirmation(label: string, first: boolean) {
  return first
    ? `${label} will start with no hosting clans.`
    : `${label} will start with the hosting clans and their settings from the previous season. Signups start empty.`;
}
export function createdSeasonMessage(label: string, count: number) {
  return `${label} created with ${count} hosting clans and their settings. Signups start empty.`;
}
