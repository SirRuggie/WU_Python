import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import ConfirmDialog from "./ConfirmDialog";

type Review = {
  manual_review_required: boolean;
  review_revision: number;
  incomplete_reason?: string;
};
export default function StrikeReviewResolution({
  warKey,
  revision,
  reason,
  canManage,
  onDirty,
  onWorking,
  onResolved,
}: {
  warKey: string;
  revision: number;
  reason?: string | null;
  canManage: boolean;
  onDirty: (dirty: boolean) => void;
  onWorking: (busy: boolean) => void;
  onResolved: () => void;
}) {
  const [open, setOpen] = useState(false),
    [note, setNote] = useState(""),
    [currentRevision, setRevision] = useState(revision);
  const [confirm, setConfirm] = useState(false),
    [busy, setBusy] = useState(false),
    [conflict, setConflict] = useState(false),
    [error, setError] = useState("");
  const pending = useRef(false),
    active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onDirty(!!note);
    return () => onDirty(false);
  }, [note, onDirty]);
  useEffect(() => {
    onWorking(busy);
    return () => onWorking(false);
  }, [busy, onWorking]);
  async function refresh() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const review = await api<Review>(
        `/strikes/tracking/review?war_key=${encodeURIComponent(warKey)}`,
      );
      if (!active.current) return;
      if (!review.manual_review_required) {
        onResolved();
        return;
      }
      if (!Number.isInteger(review.review_revision))
        throw Error("Review could not be refreshed. Try again.");
      setRevision(review.review_revision);
      setConflict(false);
    } catch (cause) {
      if (active.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "Review could not be refreshed.",
        );
    } finally {
      pending.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function resolve() {
    if (!canManage || pending.current || conflict || !note.trim()) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await api("/strikes/tracking/resolve", "POST", {
        war_key: warKey,
        revision: currentRevision,
        reason: note.trim(),
      });
      if (active.current) {
        setNote("");
        setConfirm(false);
        onResolved();
      }
    } catch (cause) {
      if (active.current) {
        setConflict(cause instanceof ApiError && cause.status === 409);
        setError(
          cause instanceof Error
            ? cause.message
            : "Resolution could not be confirmed. Refresh the review before retrying.",
        );
        setConfirm(false);
      }
    } finally {
      pending.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section
      className="strike-review-resolution"
      aria-label="Quarantined war review"
    >
      <h3>Staff review required</h3>
      <p>{reason || "This unresolved war is holding newer streak credit."}</p>
      {error && <p role="alert">{error}</p>}
      {canManage &&
        (!open ? (
          <button onClick={() => setOpen(true)}>Resolve review</button>
        ) : (
          <div>
            <label>
              Review reason
              <textarea
                autoFocus
                maxLength={500}
                value={note}
                disabled={busy}
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
            <p className="small">
              Resolving releases the streak hold. It does not add a missing
              strike.
            </p>
            {conflict ? (
              <button disabled={busy} onClick={() => void refresh()}>
                Refresh review
              </button>
            ) : (
              <button
                disabled={busy || !note.trim()}
                onClick={() => setConfirm(true)}
              >
                Resolve and release hold
              </button>
            )}
          </div>
        ))}
      {confirm && (
        <ConfirmDialog
          heading="Resolve this war review?"
          text="Release the streak hold? Existing strike history stays unchanged, and your reason is recorded."
          confirmLabel="Resolve review"
          disabled={busy}
          onCancel={() => setConfirm(false)}
          onConfirm={() => void resolve()}
        />
      )}
    </section>
  );
}
