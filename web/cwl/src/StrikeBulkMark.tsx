import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ActivityAccount, ActivityPriority } from "./strikeActivityView";

/** Explicit current-clan bulk marks; each group uses the displayed revisions. */
export default function StrikeBulkMark({
  rows,
  onSaved,
  onBusy,
  onDirty,
}: {
  rows: ActivityAccount[];
  onSaved: () => void;
  onBusy: (value: boolean) => void;
  onDirty?: (value: boolean) => void;
}) {
  const [priority, setPriority] = useState<ActivityPriority>("normal");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState(false);
  const pending = useRef(false);
  useEffect(() => {
    onDirty?.(rows.length > 0 || !!note);
    return () => onDirty?.(false);
  }, [rows.length, note, onDirty]);
  useEffect(() => () => onBusy(false), [onBusy]);
  async function save() {
    if (pending.current || conflict || !rows.length || rows.length > 50) return;
    pending.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    const groups = new Map<string, ActivityAccount[]>();
    for (const row of rows) {
      if (!row.current_clan_tag || row.left_clan) {
        setError("Refresh accounts that have left their clan.");
        pending.current = false;
        setBusy(false);
        onBusy(false);
        return;
      }
      groups.set(row.current_clan_tag, [
        ...(groups.get(row.current_clan_tag) || []),
        row,
      ]);
    }
    let added = 0,
      skipped = 0;
    try {
      for (const [clan, accounts] of groups) {
        const result = await api<{
          added_count: number;
          skipped_count: number;
        }>("/strikes/replacement-list/bulk", "POST", {
          clan_tag: clan,
          player_tags: accounts.map((row) => row.player_tag),
          priority,
          note,
          revisions: Object.fromEntries(
            accounts.map((row) => [row.player_tag, row.revision ?? 0]),
          ),
        });
        added += result.added_count;
        skipped += result.skipped_count;
      }
      onSaved();
    } catch (cause) {
      setConflict(true); // A partial group may have saved. Explicit refresh only.
      setError(
        `${added} marked; ${skipped} already marked in completed groups. ${cause instanceof Error ? cause.message : "Bulk marking stopped."} Refresh selected accounts before continuing.`,
      );
    } finally {
      pending.current = false;
      setBusy(false);
      onBusy(false);
    }
  }
  return (
    <section
      className="strike-bulk-mark"
      aria-label="Mark selected replacements"
    >
      <p>{rows.length} selected · up to 50 · existing marks are preserved</p>
      <label>
        Priority
        <select
          value={priority}
          disabled={busy || conflict}
          onChange={(e) => setPriority(e.target.value as ActivityPriority)}
        >
          <option value="normal">Normal</option>
          <option value="high">High</option>
          <option value="replace_first">Chopping Block</option>
        </select>
      </label>
      <label>
        Note
        <input
          maxLength={500}
          value={note}
          disabled={busy || conflict}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <button
        disabled={busy || conflict || !rows.length}
        onClick={() => void save()}
      >
        {busy ? "Marking…" : "Mark selected"}
      </button>
      {error && <p role="alert">{error}</p>}
      {conflict && <button onClick={onSaved}>Refresh selected accounts</button>}
    </section>
  );
}
