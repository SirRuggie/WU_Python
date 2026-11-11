import { api, type Pool } from "./api";
import { countText } from "./participationOutcome";

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

export type BonusStep = "results" | "rules" | "draw" | "approve" | "announce";
export const bonusSteps: { id: BonusStep; label: string }[] = [
  { id: "results", label: "Results" },
  { id: "rules", label: "Rules & count" },
  { id: "draw", label: "Draw" },
  { id: "approve", label: "Approve" },
  { id: "announce", label: "Announce & award" },
];
export type BonusStepState = "done" | "current" | "blocked" | "todo";
export type BonusStepView = {
  id: BonusStep;
  label: string;
  state: BonusStepState;
  reason: string;
};
/** The page knows more than the status read: it passes what it computed. */
export type BonusStepInput = {
  done?: Record<BonusStep, boolean>;
  reasons?: Partial<Record<BonusStep, string>>;
};

/** Step states for one hosting clan; the page can override from its full data. */
export function bonusStepStates(
  clan: BonusStatusClan | null | undefined,
  pool: Pool,
  mainMinimum: number | null,
  input: BonusStepInput = {},
): BonusStepView[] {
  const drawn = ["saved", "approved", "sent"].includes(clan?.draw_state || "");
  const done: Record<BonusStep, boolean> = input.done || {
    results: drawn || clan?.results_state === "captured",
    rules:
      drawn ||
      (!!clan?.active &&
        (pool !== "main" || mainMinimum !== null) &&
        !!clan.allowance_ready),
    draw: drawn,
    approve: ["approved", "sent"].includes(clan?.draw_state || ""),
    announce: clan?.draw_state === "sent",
  };
  const fallback: Record<BonusStep, string> = {
    results:
      clan?.results_state === "not_checked" ? "Results not captured" : "",
    rules: !clan?.active
      ? "Inactive host"
      : pool === "main" && mainMinimum === null
        ? "Set the Main minimum"
        : !clan.allowance_ready
          ? "Enter the bonus count"
          : "",
    draw: "",
    approve: "",
    announce: "",
  };
  const known = !!clan || !!input.done;
  const first = known ? bonusSteps.findIndex((step) => !done[step.id]) : -1;
  return bonusSteps.map((step, index) => {
    const reason = input.done
      ? input.reasons?.[step.id] || ""
      : fallback[step.id];
    const state: BonusStepState = !known
      ? "todo"
      : done[step.id]
        ? "done"
        : index === first
          ? reason
            ? "blocked"
            : "current"
          : "todo";
    return {
      ...step,
      state,
      reason: state === "blocked" ? reason : "",
    };
  });
}

/** Card state on Bonus medals: Draft, Draw saved, Approved, Sent or Inactive. */
export function bonusClanState(clan: BonusStatusClan) {
  if (clan.draw_state === "sent") return "Sent";
  if (clan.draw_state === "approved") return "Approved";
  if (clan.draw_state === "saved") return "Draw saved";
  if (!clan.active) return "Inactive";
  return "Draft";
}

/** Card line: the meet count shows before a draw; a draw replaces it. */
export function bonusClanCardText(clan: BonusStatusClan) {
  if (["saved", "approved", "sent"].includes(clan.draw_state))
    return bonusClanState(clan);
  const count =
    clan.meets_rule === null
      ? countText(clan.candidates, "candidate")
      : `${clan.meets_rule} of ${clan.candidates} meet`;
  return `${count} · ${bonusClanState(clan)}`;
}
