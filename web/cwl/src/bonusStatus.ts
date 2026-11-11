import { api, type Pool } from "./api";

export type BonusDrawState =
  "none" | "saved" | "approved" | "sent" | "cancelled";
export type BonusStatusClan = {
  tag: string;
  name: string;
  active: boolean;
  candidates: number;
  meets_rule: number | null;
  results_state: "captured" | "partial" | "not_checked";
  allowance_ready: boolean;
  draw_state: BonusDrawState;
};
export type BonusStatus = {
  season_id: number;
  cycle: string | null;
  archived: boolean;
  main_minimum: number | null;
  pools: Record<Pool, BonusStatusClan[]>;
};

/** Light read for the step bar and clan cards. It never waits on Discord or Clash. */
export async function loadBonusStatus(seasonId: string): Promise<BonusStatus> {
  const result = await api<BonusStatus>(
    `/seasons/${encodeURIComponent(seasonId)}/bonus-status`,
  );
  if (
    !result ||
    !Array.isArray(result.pools?.main) ||
    !Array.isArray(result.pools?.lazy)
  )
    throw new Error("Status unavailable");
  return result;
}

export type BonusStep =
  "results" | "eligibility" | "draw" | "approval" | "announcement";
export const bonusSteps: { id: BonusStep; label: string }[] = [
  { id: "results", label: "Results" },
  { id: "eligibility", label: "Eligibility" },
  { id: "draw", label: "Draw" },
  { id: "approval", label: "Approval" },
  { id: "announcement", label: "Announcement" },
];
export type BonusStepState = "done" | "current" | "blocked" | "todo";
export type BonusStepView = {
  id: BonusStep;
  label: string;
  state: BonusStepState;
  reason: string;
};

/** Step states for one hosting clan, from the light status read only. */
export function bonusStepStates(
  clan: BonusStatusClan | null | undefined,
  pool: Pool,
  mainMinimum: number | null,
): BonusStepView[] {
  const drawn = ["saved", "approved", "sent"].includes(clan?.draw_state || "");
  const done: Record<BonusStep, boolean> = {
    results: clan?.results_state === "captured",
    eligibility: drawn,
    draw: drawn,
    approval: ["approved", "sent"].includes(clan?.draw_state || ""),
    announcement: clan?.draw_state === "sent",
  };
  const blockers: Record<BonusStep, string> = {
    results:
      clan?.results_state === "not_checked" ? "Results not captured" : "",
    eligibility: !clan?.active
      ? "Inactive host"
      : pool === "main" && mainMinimum === null
        ? "Set the Main minimum"
        : !clan.allowance_ready
          ? "Enter the bonus count"
          : "",
    draw: "",
    approval: "",
    announcement: "",
  };
  const first = clan ? bonusSteps.findIndex((step) => !done[step.id]) : -1;
  return bonusSteps.map((step, index) => {
    const state: BonusStepState = !clan
      ? "todo"
      : done[step.id]
        ? "done"
        : index === first
          ? blockers[step.id]
            ? "blocked"
            : "current"
          : "todo";
    return {
      ...step,
      state,
      reason: state === "blocked" ? blockers[step.id] : "",
    };
  });
}

/** Card state on Bonus medals: Draft, Saved, Approved, Sent or Inactive. */
export function bonusClanState(clan: BonusStatusClan) {
  if (!clan.active) return "Inactive";
  if (clan.draw_state === "sent") return "Sent";
  if (clan.draw_state === "approved") return "Approved";
  if (clan.draw_state === "saved") return "Saved";
  return "Draft";
}
