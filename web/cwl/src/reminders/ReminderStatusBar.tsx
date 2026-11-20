import { api } from "../api";
import { StatusPill } from "../rosterUi/primitives";
import type { Campaign, CampaignState } from "../reminderCampaign";
import { shortReminderTime } from "./reminderFormat";
import type { Act, Confirmation } from "./reminderWorkspaceHelpers";

export default function ReminderStatusBar({
  base,
  state,
  draft,
  dirty,
  disabled,
  act,
  load,
  setNotice,
  setConfirmation,
}: {
  base: string;
  state: CampaignState;
  draft: Campaign;
  dirty: boolean;
  disabled: boolean;
  act: Act;
  load: () => Promise<void>;
  setNotice: (notice: string) => void;
  setConfirmation: (confirmation: Confirmation | null) => void;
}) {
  const next = state.schedule
    ?.filter(
      (item) =>
        item.message_id !== "roster" &&
        (item.variant === "main" || item.variant === "lazy") &&
        draft.messages[item.message_id]?.enabled &&
        draft.messages[item.message_id]?.variants[item.variant]?.enabled !==
          false &&
        item.run_at &&
        !["sent", "skipped", "cancelled"].includes(item.status || "") &&
        new Date(item.run_at) > new Date(),
    )
    .sort((a, b) => Date.parse(a.run_at!) - Date.parse(b.run_at!))[0]?.run_at;
  return (
    <div className="reminder-status">
      <StatusPill
        tone={
          !state.activated ? "neutral" : draft.paused ? "warning" : "success"
        }
      >
        {!state.activated ? "Off" : draft.paused ? "Paused" : "On"}
      </StatusPill>
      {!state.worker_ready ? (
        <span role="status">
          <StatusPill tone="danger">Reminders offline</StatusPill>
        </span>
      ) : state.activated && !state.schedule_synced ? (
        <span role="status">
          <StatusPill tone="warning">Loading changes…</StatusPill>
        </span>
      ) : null}
      {!state.activated && (
        <span className="small">Save changes to turn reminders on.</span>
      )}
      {state.activated && !draft.paused && next && (
        <span className="small"> · next {shortReminderTime(next)}</span>
      )}
      {state.activated && (
        <div
          className="reminder-pause-control"
          role="group"
          aria-label="Reminder scheduling"
          tabIndex={dirty ? 0 : undefined}
          aria-describedby={dirty ? "reminder-pause-reason" : undefined}
          title={dirty ? "Save or discard edits first." : undefined}
        >
          <button
            disabled={disabled || dirty}
            aria-label={draft.paused ? "Resume reminders" : "Pause reminders"}
            aria-describedby={dirty ? "reminder-pause-reason" : undefined}
            onClick={() => {
              setConfirmation({
                text: draft.paused
                  ? "Resume all signup reminders? This resumes their scheduled messages."
                  : "Pause all signup reminders? This pauses their scheduled messages.",
                confirmLabel: draft.paused
                  ? "Resume reminders"
                  : "Pause reminders",
                action: () =>
                  void act(async () => {
                    const paused = !draft.paused;
                    await api(base + "/pause", "POST", {
                      generation: state.generation,
                      paused,
                    });
                    await load();
                    setNotice(
                      paused
                        ? "Scheduled messages paused."
                        : "Scheduled messages resumed. The schedule is updating.",
                    );
                  }),
              });
            }}
          >
            {draft.paused ? "Resume" : "Pause"}
          </button>
          {dirty && (
            <small id="reminder-pause-reason" className="reminder-pause-reason">
              Save or discard edits first.
            </small>
          )}
        </div>
      )}
    </div>
  );
}
