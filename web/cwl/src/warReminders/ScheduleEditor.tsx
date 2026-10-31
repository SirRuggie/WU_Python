import { useState } from "react";
import ChannelCombobox from "../ChannelCombobox";
import type { AnnouncementChannel } from "../announcements";
import { addReminderTime, timeLabel, type ReminderSettings } from "./types";

type Props = {
  settings: ReminderSettings;
  channels: AnnouncementChannel[];
  disabled: boolean;
  onChange: (patch: Partial<ReminderSettings>) => void;
};

export default function ScheduleEditor({
  settings,
  channels,
  disabled,
  onChange,
}: Props) {
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState(60);
  const [error, setError] = useState("");

  function addTime() {
    try {
      onChange({ minutes: addReminderTime(settings.minutes, amount, unit) });
      setAmount("");
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <div className="war-intro">
        <div>
          <h3>War reminders</h3>
          <p>
            Choose when and where to remind players with unused attacks.
            Supports regular wars and CWL.
          </p>
        </div>
        <label className="war-toggle">
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={disabled}
            onChange={(e) => onChange({ enabled: e.target.checked })}
          />
          {settings.enabled ? "Enabled" : "Disabled"}
        </label>
      </div>
      <fieldset disabled={disabled}>
        <ChannelCombobox
          nameOnly
          label="Reminder channel"
          channels={channels.filter((c) => [0, 5].includes(c.type))}
          value={settings.channel_id}
          disabled={disabled}
          onChange={(value) => onChange({ channel_id: value })}
        />
        <label>
          Remind who?
          <select
            value={settings.audience}
            onChange={(e) =>
              onChange({
                audience: e.target.value as ReminderSettings["audience"],
              })
            }
          >
            <option value="remaining">Players with attacks left</option>
            <option value="zero">Only players who have not attacked</option>
          </select>
        </label>
        <div className="war-schedule">
          <h4>Reminder timeline</h4>
          <label className="war-toggle">
            <input
              type="checkbox"
              checked={settings.war_started}
              onChange={(e) => onChange({ war_started: e.target.checked })}
            />
            When war starts
          </label>
          <p className="small">
            Choose any combination of times before war ends.
          </p>
          <div className="war-chips">
            {settings.minutes.map((minutes) => (
              <button
                type="button"
                key={minutes}
                aria-label={`Remove ${timeLabel(minutes)} reminder`}
                onClick={() =>
                  onChange({
                    minutes: settings.minutes.filter(
                      (value) => value !== minutes,
                    ),
                  })
                }
              >
                {timeLabel(minutes)} before end{" "}
                <span aria-hidden="true">×</span>
              </button>
            ))}
          </div>
          <details className="war-disclosure">
            <summary>Add reminder times</summary>
            <div className="war-time-input">
              <label>
                Custom time
                <input
                  type="number"
                  min={1 / unit}
                  max={1440 / unit}
                  step="any"
                  placeholder="e.g. 8"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </label>
              <label>
                Unit
                <select
                  value={unit}
                  onChange={(e) => setUnit(Number(e.target.value))}
                >
                  <option value={60}>Hours</option>
                  <option value={1}>Minutes</option>
                </select>
              </label>
              <button type="button" onClick={addTime} disabled={!amount}>
                Add time
              </button>
            </div>
            {error && <p role="alert">{error}</p>}
            <div className="war-presets">
              <small>Quick add</small>
              {[720, 480, 60, 30]
                .filter((minutes) => !settings.minutes.includes(minutes))
                .map((minutes) => (
                  <button
                    type="button"
                    key={minutes}
                    onClick={() =>
                      onChange({
                        minutes: addReminderTime(
                          settings.minutes,
                          String(minutes),
                          1,
                        ),
                      })
                    }
                  >
                    + {timeLabel(minutes)}
                  </button>
                ))}
            </div>
          </details>
        </div>
      </fieldset>
    </>
  );
}
