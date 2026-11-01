import { useRef, useState } from "react";
import { api, ApiError } from "./api";

/** An explicit staff mark, separate from placement and weight edits. */
export default function RosterFillerCheckbox({
  seasonId,
  tag,
  name,
  value,
  markRevision,
  revision,
  disabled = false,
  onChanged,
}: {
  seasonId: string;
  tag: string;
  name: string;
  value: boolean;
  markRevision: number;
  revision: number;
  disabled?: boolean;
  onChanged: () => void | Promise<void>;
}) {
  const pending = useRef(false);
  const [accessLost, setAccessLost] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function change(next: boolean) {
    if (disabled || accessLost || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await api(
        `/seasons/${encodeURIComponent(seasonId)}/roster-filler/${encodeURIComponent(tag)}`,
        "PATCH",
        {
          revision,
          roster_filler: next,
          mark_revision: markRevision,
        },
      );
      await onChanged();
    } catch (cause) {
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setAccessLost(true);
        // Refresh/clear protected parent state without replaying this mutation.
        try {
          await onChanged();
        } catch {
          /* The original permission failure remains visible. */
        }
      }
      setError(
        cause instanceof Error
          ? cause.message
          : "Couldn't save filler mark. Refresh and try again.",
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="roster-filler-control">
      <label
        style={{ minHeight: 44, display: "flex", alignItems: "center", gap: 8 }}
      >
        <input
          type="checkbox"
          aria-label={`Filler: ${name}`}
          checked={value}
          disabled={disabled || accessLost || busy}
          onChange={(e) => void change(e.target.checked)}
        />
        Filler{busy ? " · Saving…" : ""}
      </label>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
