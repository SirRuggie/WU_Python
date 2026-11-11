import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import FilterChips from "../FilterChips";
import SearchPicker from "../SearchPicker";
import { Button } from "../rosterUi/primitives";
import {
  API_BASE,
  type ClockRun,
  type ClockSettings,
} from "./worldClocksModel";

export default function ClockSettingsPanel({
  settings,
  categories,
  channelsAvailable,
  onSaved,
  onConflict,
  onDirty,
}: {
  settings: ClockSettings;
  categories: { id: string; name: string }[];
  channelsAvailable: boolean;
  onSaved: (settings: ClockSettings) => void;
  onConflict: (notice: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty =
    draft.category_id !== settings.category_id ||
    draft.time_format !== settings.time_format ||
    draft.interval_minutes !== settings.interval_minutes;

  // Reset the draft only when the saved settings change (new revision), not on
  // every page reload, so unsaved choices survive a clock save elsewhere.
  useEffect(() => setDraft(settings), [settings.revision]);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);

  async function save() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ settings: ClockSettings }>(
        `${API_BASE}/settings`,
        "PUT",
        {
          revision: settings.revision,
          category_id: draft.category_id,
          time_format: draft.time_format,
          interval_minutes: draft.interval_minutes,
        },
      );
      onSaved(result.settings);
      setNotice("Saved. Clocks use it at the next update.");
    } catch (reason) {
      const text = reason instanceof Error ? reason.message : "Saving failed.";
      if (reason instanceof ApiError && reason.status === 409) onConflict(text);
      else setError(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="world-clock-settings">
      <div className="world-clock-setting">
        <SearchPicker
          label="New channels go in"
          options={categories.map((row) => ({
            value: row.id,
            label: row.name,
          }))}
          value={draft.category_id || ""}
          fallback={
            draft.category_id
              ? {
                  value: draft.category_id,
                  label: "Selected category unavailable",
                }
              : undefined
          }
          placeholder="Select a category"
          searchPlaceholder="Search categories"
          emptyText="No categories match."
          disabled={busy || !channelsAvailable}
          clearable
          onChange={(value) =>
            setDraft({ ...draft, category_id: value || null })
          }
        />
        <p className="world-clock-help">
          New voice channels copy this category's permissions.
        </p>
      </div>
      <div className="world-clock-setting">
        <span className="world-clock-label">Time format</span>
        <FilterChips
          label="Time format"
          variant="pill"
          value={draft.time_format}
          disabled={busy}
          options={[
            { value: "12h", label: "9:30pm" },
            { value: "24h", label: "21:30" },
          ]}
          onChange={(time_format) => setDraft({ ...draft, time_format })}
        />
      </div>
      <div className="world-clock-setting">
        <span className="world-clock-label">Update every</span>
        <FilterChips
          label="Update every"
          variant="pill"
          value={draft.interval_minutes}
          disabled={busy}
          options={[
            { value: 6, label: "6 minutes" },
            { value: 10, label: "10 minutes" },
          ]}
          onChange={(interval_minutes) =>
            setDraft({ ...draft, interval_minutes })
          }
        />
        <p className="world-clock-help">
          Discord allows about 2 name changes per channel in 10 minutes. Use 10
          minutes if Recent updates often shows waits.
        </p>
      </div>
      {error && (
        <p className="world-clock-error" role="alert">
          {error}
        </p>
      )}
      <div className="world-clock-settings-save">
        <span role="status">
          {dirty ? "Unsaved changes" : notice || "All changes saved"}
        </span>
        {dirty && (
          <Button variant="primary" disabled={busy} onClick={() => void save()}>
            {busy ? "Saving…" : "Save settings"}
          </Button>
        )}
      </div>
    </div>
  );
}

export function RecentUpdates({ runs }: { runs: ClockRun[] }) {
  return (
    <details className="world-clock-history">
      <summary>Recent updates</summary>
      <ul>
        {runs.map((run) => (
          <li key={run.at}>
            {new Date(run.at).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })}{" "}
            {run.discord_unavailable ? (
              "· Discord was unavailable. Nothing was renamed."
            ) : (
              <>
                · {run.renamed ?? 0} renamed · {run.unchanged ?? 0} already
                right
                {run.waited ? ` · ${run.waited} waited (Discord limit)` : ""}
                {run.problem ? ` · ${run.problem} with a problem` : ""}
                {run.moved ? " · order fixed" : ""}
              </>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
