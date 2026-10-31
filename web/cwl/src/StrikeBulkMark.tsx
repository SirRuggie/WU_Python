import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { ActivityAccount, ActivityPriority } from "./strikeActivityView";

/** Explicit current-clan bulk marks; each group uses the displayed revisions. */
export default function StrikeBulkMark({
  rows,
  onSaved,
  onRemaining,
  onRefresh,
  onBusy,
  onDirty,
}: {
  rows: ActivityAccount[];
  onSaved: () => void;
  onRemaining?: (tags: string[]) => void;
  onRefresh?: () => Promise<boolean | undefined>;
  onBusy: (value: boolean) => void;
  onDirty?: (value: boolean) => void;
}) {
  const [priority, setPriority] = useState<ActivityPriority>("normal");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    onDirty?.(rows.length > 0 || !!note);
    return () => onDirty?.(false);
  }, [rows.length, note, onDirty]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onBusy(false);
    };
  }, [onBusy]);
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
    const completed = new Set<string>();
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
        for (const row of accounts) completed.add(row.player_tag);
      }
      if (mounted.current) onSaved();
    } catch (cause) {
      if (!mounted.current) return;
      const data =
        cause instanceof ApiError &&
        cause.responseData &&
        typeof cause.responseData === "object"
          ? (cause.responseData as Record<string, unknown>)
          : null;
      if (data) {
        if (Number.isInteger(data.added_count) && Number(data.added_count) >= 0)
          added += Number(data.added_count);
        if (
          Number.isInteger(data.skipped_count) &&
          Number(data.skipped_count) >= 0
        )
          skipped += Number(data.skipped_count);
        for (const key of ["added", "skipped"])
          if (Array.isArray(data[key]))
            for (const tag of data[key])
              if (
                typeof tag === "string" &&
                rows.some((row) => row.player_tag === tag)
              )
                completed.add(tag);
      }
      const failed = rows.filter((row) => !completed.has(row.player_tag));
      onRemaining?.(failed.map((row) => row.player_tag));
      setConflict(true);
      setError(
        `${added} marked; ${skipped} already marked. Not completed or unconfirmed: ${failed.map((row) => row.player_name).join(", ") || "none"}. ${cause instanceof Error ? cause.message : "Bulk marking stopped."} Refresh before continuing.`,
      );
    } finally {
      pending.current = false;
      if (mounted.current) {
        setBusy(false);
        onBusy(false);
      }
    }
  }
  return (
    <section
      className="strike-bulk-mark"
      aria-label="Mark selected replacements"
    >
      <p>{rows.length} selected · up to 50 · existing marks are preserved</p>
      <ul aria-label="Selected accounts" className="strike-bulk-accounts">
        {rows.map((row) => (
          <li key={row.player_tag}>
            <strong>{row.player_name}</strong> {row.player_tag} ·{" "}
            {row.current_clan_name || row.current_clan_tag}
          </li>
        ))}
      </ul>
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
      {conflict && (
        <button
          disabled={busy}
          onClick={async () => {
            if (!onRefresh) {
              onSaved();
              return;
            }
            setBusy(true);
            onBusy(true);
            try {
              if (await onRefresh()) {
                setConflict(false);
                setError("");
              } else
                setError(
                  "Refresh failed. Saved outcomes remain unconfirmed; no retry was sent.",
                );
            } finally {
              if (mounted.current) {
                setBusy(false);
                onBusy(false);
              }
            }
          }}
        >
          Refresh selected accounts
        </button>
      )}
    </section>
  );
}
