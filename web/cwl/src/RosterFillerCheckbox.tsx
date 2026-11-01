import { useRef, useState } from "react";
import { api } from "./api";

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
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function change(next: boolean) {
    if (disabled || pending.current) return;
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
          disabled={disabled || busy}
          onChange={(e) => void change(e.target.checked)}
        />
        Filler{busy ? " · Saving…" : ""}
      </label>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
