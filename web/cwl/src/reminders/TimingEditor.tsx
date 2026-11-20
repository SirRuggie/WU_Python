import ReminderNumberField from "./ReminderNumberField";
import type { Timing } from "../reminderCampaign";

export default function TimingEditor({
  value,
  onChange,
  deadline = false,
  onInvalidChange,
}: {
  value: Timing | string;
  onChange: (value: Timing) => void;
  deadline?: boolean;
  onInvalidChange?: (field: string, invalid: boolean) => void;
}) {
  const rule: Timing = typeof value === "string" ? { at: value } : value;
  const mode = deadline
    ? rule.at
      ? "specific"
      : "monthly"
    : rule.mode || "manual";
  const update = (patch: Timing) => onChange({ ...rule, ...patch });
  return (
    <div className="reminder-fields">
      <label>
        Timing
        <select
          value={mode}
          onChange={(event) =>
            onChange(
              event.target.value === "specific"
                ? { ...(deadline ? {} : { mode: "specific" }), at: "" }
                : event.target.value === "monthly"
                  ? {
                      ...(deadline ? {} : { mode: "monthly" }),
                      day: 1,
                      hour: 17,
                      minute: 0,
                    }
                  : {
                      mode: event.target.value,
                      ...(event.target.value === "manual"
                        ? {}
                        : { offset_minutes: 1440 }),
                    },
            )
          }
        >
          {!deadline && <option value="manual">Manual only</option>}
          <option value="specific">Specific date and time</option>
          <option value="monthly">Monthly date rule</option>
          {!deadline && (
            <>
              <option value="after_open">After signup opens</option>
              <option value="before_close">Before signup closes</option>
              {mode === "legacy_chain" && (
                <option value="legacy_chain">
                  After previous message (existing)
                </option>
              )}
            </>
          )}
        </select>
      </label>
      {mode === "specific" && (
        <label>
          Date and time
          <input
            type="datetime-local"
            value={(rule.at || "").slice(0, 16)}
            onChange={(event) => update({ at: event.target.value })}
          />
        </label>
      )}
      {mode === "monthly" && (
        <>
          <label>
            Count from
            <select
              value={rule.month_end_offset_days !== undefined ? "end" : "day"}
              onChange={(event) => {
                const next = { ...rule };
                delete next.day;
                delete next.month_end_offset_days;
                onChange({
                  ...next,
                  ...(event.target.value === "end"
                    ? { month_end_offset_days: 2 }
                    : { day: 1 }),
                });
              }}
            >
              <option value="day">Day of month</option>
              <option value="end">Days before month ends</option>
            </select>
          </label>
          <ReminderNumberField
            key={rule.month_end_offset_days !== undefined ? "end" : "day"}
            label={
              rule.month_end_offset_days !== undefined
                ? "Days before month ends"
                : "Day of month"
            }
            min={rule.month_end_offset_days !== undefined ? 0 : 1}
            max={rule.month_end_offset_days !== undefined ? 27 : 31}
            value={rule.month_end_offset_days ?? rule.day ?? 1}
            onInvalidChange={(invalid) =>
              onInvalidChange?.("monthly-day", invalid)
            }
            onChange={(number) =>
              update({
                [rule.month_end_offset_days !== undefined
                  ? "month_end_offset_days"
                  : "day"]: number,
              })
            }
          />
          <label>
            Time
            <input
              type="time"
              value={`${String(rule.hour ?? 17).padStart(2, "0")}:${String(rule.minute ?? 0).padStart(2, "0")}`}
              onChange={(event) => {
                const [hour, minute] = event.target.value
                  .split(":")
                  .map(Number);
                update({ hour, minute });
              }}
            />
          </label>
        </>
      )}
      {["after_open", "before_close", "legacy_chain"].includes(mode) && (
        <div>
          <ReminderNumberField
            label="Offset in minutes"
            min={0}
            value={rule.offset_minutes ?? 1440}
            onChange={(number) => update({ offset_minutes: number })}
            onInvalidChange={(invalid) => onInvalidChange?.("offset", invalid)}
          />
          {mode === "legacy_chain" && (
            <small>After {rule.after || "previous reminder"}.</small>
          )}
        </div>
      )}
    </div>
  );
}
