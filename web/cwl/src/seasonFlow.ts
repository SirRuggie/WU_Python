import { api, ApiError, type Season } from "./api";
import { seasonMonth, seasonMonthLabel } from "./seasonLabels";
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
        ? `Signups for ${season.label} are open, but members cannot see the season. Show it to members?`
        : hidden
          ? `Members cannot see ${season.label} yet. Show it to members and open signups?`
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
      if (!(error instanceof ApiError) || error.status <= 0)
        throw new Error(
          plan.opened
            ? "Signups may not have opened. Refreshing to check…"
            : "Signups may not have closed. Refreshing to check…",
        );
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
    ? `${label} will start with no hosting clans. Signups start empty.`
    : `${label} will start with the hosting clans and their settings from the previous season. Signups start empty.`;
}
export function createdSeasonMessage(label: string, count: number) {
  return `${label} created with ${count} hosting clans and their settings. Signups start empty.`;
}

/**
 * Create the next month season (if missing), show it to members, optionally
 * open its signups. State is re-read first so a retry skips finished steps; each
 * step runs only after the previous one succeeded.
 */
export async function finishMonth(cycle: string, openSignups: boolean) {
  const name = seasonMonthLabel({ label: cycle });
  const create = `create ${name}`;
  const show = `show ${name} to members`;
  const open = `open ${name} signups`;
  const done: string[] = [];
  let steps = [create, show, ...(openSignups ? [open] : [])];
  try {
    let state = await api<SeasonState>("/seasons");
    let next = state.seasons.find((item) => seasonMonth(item) === cycle);
    if (next) steps = steps.slice(1);
    else {
      await api("/seasons", "POST", { label: cycle, signup_open: false });
      done.push(create);
      state = await api<SeasonState>("/seasons");
      next = state.seasons.find((item) => seasonMonth(item) === cycle);
      if (!next) throw new Error("The new season was not found.");
    }
    if (state.member_season.season_id !== next.id)
      await api("/member-season", "PUT", {
        season_id: next.id,
        revision: state.member_season.revision,
      });
    done.push(show);
    if (openSignups && !next.signup_open) {
      await api(`/seasons/${next.id}`, "PATCH", {
        signup_open: true,
        expected_signup_open: false,
      });
    }
    if (openSignups) done.push(open);
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : "Request failed.";
    const left = steps.filter((step) => !done.includes(step));
    throw new Error(
      `${reason} Done: ${done.join(", ") || "nothing"}. Not done: ${left.join(", ")}.`,
    );
  }
}
