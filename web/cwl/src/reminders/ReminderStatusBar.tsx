import { api } from "../api";
import type { Campaign, CampaignState } from "../reminderCampaign";
import type { Act, Confirmation } from "./reminderWorkspaceHelpers";

export default function ReminderStatusBar({
  base,
  state,
  draft,
  dirty,
  busy,
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
  busy: boolean;
  disabled: boolean;
  act: Act;
  load: () => Promise<void>;
  setNotice: (notice: string) => void;
  setConfirmation: (confirmation: Confirmation | null) => void;
}) {
  return (
    <div className="reminder-status">
      <span className="badge">
        {!state.activated ? "Off" : draft.paused ? "Paused" : "On"}
      </span>
      {!state.worker_ready ? (
        <span className="notice error" role="status">
          Bot offline
        </span>
      ) : state.activated && !state.schedule_synced ? (
        <span className="notice" role="status">
          Waiting for changes to load in Discord
        </span>
      ) : null}
      <div className="reminder-control-actions">
        <button
          disabled={busy}
          onClick={() => {
            if (!dirty) void act(load);
            else
              setConfirmation({
                text: "Discard unsaved reminder edits and reload the saved reminders?",
                action: () => void act(load),
              });
          }}
        >
          Refresh
        </button>
        <button
          disabled={disabled || dirty}
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
                      : "Scheduled messages resumed. The bot is updating its schedule.",
                  );
                }),
            });
          }}
        >
          {draft.paused ? "Resume reminders" : "Pause reminders"}
        </button>
      </div>
    </div>
  );
}
