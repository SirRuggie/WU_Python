import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import ConfirmDialog from "./ConfirmDialog";
import useReplacementRevision from "./useReplacementRevision";
import type { Priority } from "./replacementTypes";
const labels: Record<Priority, string> = {
  normal: "Normal",
  high: "High",
  replace_first: "Chopping Block",
};

/** Single-account editor uses the displayed revision; conflict reload is explicit. */
export default function StrikeReplacementRow({
  tag,
  canManage,
  onDirty,
  onWorking,
}: {
  tag: string;
  canManage: boolean;
  onDirty: (dirty: boolean) => void;
  onWorking: (busy: boolean) => void;
}) {
  const baseline = useReplacementRevision(tag);
  const [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false);
  const [priority, setPriority] = useState<Priority>("normal"),
    [note, setNote] = useState("");
  const [error, setError] = useState(""),
    [conflict, setConflict] = useState(false);
  const [confirm, setConfirm] = useState<"clear" | "discard" | null>(null);
  const pending = useRef(false);
  const dirty =
    editing &&
    (priority !== (baseline.saved?.priority || "normal") ||
      note !== (baseline.saved?.note || ""));
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    onWorking(busy);
    return () => onWorking(false);
  }, [busy, onWorking]);
  async function save(clear = false) {
    if (!canManage || pending.current || baseline.revision === null || conflict)
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await api(
        `/strikes/replacement-list/${encodeURIComponent(tag)}`,
        clear ? "DELETE" : "PUT",
        clear
          ? { revision: baseline.revision }
          : { revision: baseline.revision, priority, note },
      );
      setEditing(false);
      setConfirm(null);
      await baseline.reload();
    } catch (cause) {
      const stale = cause instanceof ApiError && cause.status === 409;
      setConflict(stale);
      setError(
        stale
          ? "Changed by someone else · Reload"
          : cause instanceof Error
            ? cause.message
            : "Could not save priority.",
      );
      setConfirm(null);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      className="strike-replacement-row"
      aria-label="Replacement priority"
    >
      <p>
        Replacement:{" "}
        {baseline.loading
          ? "Loading…"
          : baseline.saved?.priority
            ? labels[baseline.saved.priority]
            : "Not marked"}
        {canManage && !editing && (
          <button
            type="button"
            disabled={busy || baseline.revision === null}
            onClick={() => {
              setPriority(baseline.saved?.priority || "normal");
              setNote(baseline.saved?.note || "");
              setError("");
              setConflict(false);
              setEditing(true);
            }}
          >
            Edit
          </button>
        )}
      </p>
      {!editing && baseline.saved?.note && (
        <p className="replacement-note">{baseline.saved.note}</p>
      )}
      {(error || baseline.error) && (
        <p role="alert">{error || baseline.error}</p>
      )}
      {(conflict || baseline.error) && (
        <button
          type="button"
          disabled={busy || baseline.loading}
          onClick={async () => {
            await baseline.reload();
            setConflict(false);
            setError("");
          }}
        >
          Reload
        </button>
      )}
      {editing && canManage && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            Priority
            <select
              value={priority}
              disabled={busy}
              onChange={(event) => setPriority(event.target.value as Priority)}
            >
              {Object.entries(labels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Note
            <textarea
              value={note}
              maxLength={500}
              disabled={busy}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={busy || baseline.revision === null || conflict}
          >
            Save priority
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => (dirty ? setConfirm("discard") : setEditing(false))}
          >
            Cancel
          </button>
          {baseline.saved?.is_manual && (
            <button
              type="button"
              disabled={busy || conflict}
              onClick={() => setConfirm("clear")}
            >
              Clear priority
            </button>
          )}
        </form>
      )}
      {confirm && (
        <ConfirmDialog
          heading={confirm === "clear" ? "Clear priority?" : "Unsaved changes"}
          text={
            confirm === "clear"
              ? "Strike history stays."
              : "Discard your unsaved replacement changes?"
          }
          confirmLabel={confirm === "clear" ? "Clear" : "Discard"}
          cancelLabel={confirm === "clear" ? "Keep" : "Keep editing"}
          disabled={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            if (confirm === "clear") void save(true);
            else {
              setEditing(false);
              setConfirm(null);
            }
          }}
        />
      )}
    </section>
  );
}
