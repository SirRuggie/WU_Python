import ReminderNumberField from "./ReminderNumberField";
import { shortReminderTime } from "./reminderFormat";
import { reminderNextSend } from "./reminderList";
import type { Campaign, Occurrence } from "../reminderCampaign";
import SignupDateField from "./SignupDateField";
import TimingEditor from "./TimingEditor";
import { clone } from "./reminderWorkspaceHelpers";

export default function ReminderScheduleTab({
  draft,
  cycle,
  signupOpen,
  disabled,
  edit,
  schedule,
  onInvalidChange,
}: {
  draft: Campaign;
  cycle: string | null;
  signupOpen: boolean;
  disabled: boolean;
  edit: (next: Campaign) => void;
  schedule: Occurrence[];
  onInvalidChange: (field: string, invalid: boolean) => void;
}) {
  return (
    <div className="card">
      <p className="reminder-timezone">Dates and times use {draft.timezone}.</p>
      <fieldset disabled={disabled}>
        <legend>Signup window &amp; reminder timing</legend>
        <div className="signup-date-grid">
          {draft.messages.signup && (
            <SignupDateField
              label="Opening announcement"
              value={draft.messages.signup.schedule}
              cycle={cycle}
              timezone={draft.timezone}
              onChange={(value) => {
                const next = clone(draft);
                if (!next.messages.signup) return;
                next.messages.signup.schedule = value;
                edit(next);
              }}
            />
          )}
          <SignupDateField
            label="Advertised signup deadline"
            deadline
            value={draft.signup_deadline}
            cycle={cycle}
            timezone={draft.timezone}
            onChange={(value) => edit({ ...draft, signup_deadline: value })}
          />
        </div>
        <p className="small">
          Dashboard signups are currently {signupOpen ? "open" : "closed"}.
          Reminders do not open or close website signups or external forms.
        </p>
        <h3>Reminder frequency</h3>
        <label>
          Plan
          <select
            value={
              draft.reminder_sequence.enabled
                ? draft.reminder_sequence.mode
                : "individual"
            }
            onChange={(event) =>
              edit({
                ...draft,
                reminder_sequence:
                  event.target.value === "individual"
                    ? { enabled: false }
                    : {
                        enabled: true,
                        mode: event.target.value,
                        count: 4,
                        interval_hours: 48,
                        final_hours: 3,
                        min_gap_hours: 3,
                      },
              })
            }
          >
            <option value="individual">Individual message times</option>
            <option value="evenly">Evenly spaced reminders</option>
            <option value="interval">Every set number of hours</option>
          </select>
        </label>
        {draft.reminder_sequence.enabled ? (
          <div className="reminder-fields">
            {(["count", "interval_hours", "final_hours"] as const)
              .filter(
                (key) =>
                  key !== "count" || draft.reminder_sequence.mode === "evenly",
              )
              .filter(
                (key) =>
                  key !== "interval_hours" ||
                  draft.reminder_sequence.mode === "interval",
              )
              .map((key) => (
                <ReminderNumberField
                  key={key}
                  label={
                    {
                      count: "Total reminders",
                      interval_hours: "Hours between reminders",
                      final_hours: "Final reminder hours before close",
                    }[key]
                  }
                  min={1}
                  max={key === "count" ? 10 : 744}
                  value={draft.reminder_sequence[key] ?? 1}
                  onInvalidChange={(invalid) =>
                    onInvalidChange(`sequence:${key}`, invalid)
                  }
                  onChange={(number) =>
                    edit({
                      ...draft,
                      reminder_sequence: {
                        ...draft.reminder_sequence,
                        [key]: number,
                      },
                    })
                  }
                />
              ))}
          </div>
        ) : (
          Object.entries(draft.messages)
            .filter(([id]) => id !== "signup" && id !== "roster")
            .map(([id, item]) => (
              <details key={id}>
                <summary>
                  {item.label || id} ·{" "}
                  {shortReminderTime(
                    reminderNextSend(draft, id, "all", schedule),
                    draft.timezone,
                  )}
                </summary>
                <TimingEditor
                  value={item.schedule}
                  onInvalidChange={(field, invalid) =>
                    onInvalidChange(`message:${id}:${field}`, invalid)
                  }
                  onChange={(value) => {
                    const next = clone(draft);
                    next.messages[id].schedule = value;
                    edit(next);
                  }}
                />
              </details>
            ))
        )}
        <details>
          <summary>Advanced</summary>
          <label>
            Schedule timezone
            <input
              value={draft.timezone}
              onChange={(event) =>
                edit({ ...draft, timezone: event.target.value })
              }
              placeholder="America/New_York"
            />
          </label>
          {draft.reminder_sequence.enabled && (
            <ReminderNumberField
              label="Minimum hours between reminders"
              min={1}
              max={24}
              value={draft.reminder_sequence.min_gap_hours ?? 3}
              onInvalidChange={(invalid) =>
                onInvalidChange("sequence:min_gap_hours", invalid)
              }
              onChange={(number) =>
                edit({
                  ...draft,
                  reminder_sequence: {
                    ...draft.reminder_sequence,
                    min_gap_hours: number,
                  },
                })
              }
            />
          )}
        </details>
      </fieldset>
    </div>
  );
}
