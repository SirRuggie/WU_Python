import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool } from "./api";
import ActionPanel from "./ActionPanel";
import ConfirmDialog from "./ConfirmDialog";
import AnnouncementPostReview from "./AnnouncementPostReview";
import AnnouncementPostCopyEditor from "./AnnouncementPostCopyEditor";
import {
  postUpdateActive,
  validPostCopy,
  checkedPostReview,
  type PostCopy,
  type PostReview,
} from "./announcementPostUpdate";
import "./announcementPostUpdate.css";

type Props = {
  seasonId: string;
  cycle: string;
  pool: Pool;
  generation: string;
  copy: PostCopy;
  allowed: boolean;
  onUpdated: () => void;
  onDirty?: (pool: Pool, dirty: boolean) => void;
};
const clone = (value: PostCopy): PostCopy => ({
  title: value.title,
  body: value.body,
  buttons: value.buttons.map((button) => ({ ...button })),
});
const text = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The post review is unavailable. Try again.";
export default function AnnouncementPostUpdate(props: Props) {
  const [open, setOpen] = useState(false),
    [value, setValue] = useState(() => clone(props.copy));
  const [review, setReview] = useState<PostReview | null>(null),
    [nonce, setNonce] = useState<string | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [pollTick, setPollTick] = useState(0);
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [confirm, setConfirm] = useState(false),
    [discard, setDiscard] = useState(false);
  const [future, setFuture] = useState(true),
    [editing, setEditing] = useState(true);
  const opener = useRef<HTMLButtonElement>(null),
    running = useRef(false),
    alive = useRef(true),
    epoch = useRef(0),
    current = useRef(props);
  current.current = props;
  const storageKey = `wu-post-review:${props.seasonId}:${props.pool}:${props.cycle}`;
  const base = `/seasons/${encodeURIComponent(props.seasonId)}/manage-bridge/${props.pool}/post-updates`;
  const readSequence = useRef(0);
  const futureChosen = useRef(false);
  const initial = useRef(JSON.stringify(props.copy));
  const reviewedGeneration = useRef(props.generation);
  const dirty = open && editing && JSON.stringify(value) !== initial.current;
  useEffect(() => {
    props.onDirty?.(props.pool, dirty);
    return () => props.onDirty?.(props.pool, false);
  }, [dirty, props.pool, props.onDirty]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const remember = (key: string | null) => {
    setNonce(key);
    try {
      if (key) sessionStorage.setItem(storageKey, key);
      else sessionStorage.removeItem(storageKey);
    } catch {
      /* Storage is optional; the current view still works. */
    }
  };
  const accept = (response: PostReview) => {
    const next = checkedPostReview(response);
    setError("");
    reviewedGeneration.current = next.generation;
    setReview(next);
    setValue(clone(next.candidate));
    setEditing(false);
    if (!futureChosen.current) setFuture(next.future_months);
    if (next.status === "done") {
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* Optional. */
      }
      current.current.onUpdated();
    }
  };
  const failed = (reason: unknown) => {
    if (
      reason instanceof ApiError &&
      (reason.status === 401 || reason.status === 403)
    ) {
      setDenied(true);
      remember(null);
      setReview(null);
      setValue({ title: "", body: "", buttons: [] });
      setEditing(false);
      setConfirm(false);
    } else if (reason instanceof ApiError && reason.status === 404) {
      remember(null);
      setReview((previous) =>
        previous
          ? { ...previous, status: "expired", worker_ready: false }
          : null,
      );
      if (!review) setEditing(true);
    }
    setError(text(reason));
  };
  const read = async (key: string, ticket: number) => {
    const sequence = ++readSequence.current;
    try {
      const next = await api<PostReview>(`${base}/${key}`);
      if (
        alive.current &&
        epoch.current === ticket &&
        sequence === readSequence.current
      )
        accept(next);
    } catch (reason) {
      if (
        alive.current &&
        epoch.current === ticket &&
        sequence === readSequence.current
      )
        failed(reason);
    } finally {
      if (
        alive.current &&
        epoch.current === ticket &&
        sequence === readSequence.current
      )
        setPollTick((value) => value + 1);
    }
  };
  useEffect(() => {
    if (!open || !nonce || !postUpdateActive(review)) return;
    const ticket = epoch.current;
    const timer = window.setTimeout(
      () => {
        void read(nonce, ticket);
      },
      error ? 10000 : 2000,
    );
    return () => window.clearTimeout(timer);
  }, [open, nonce, review, pollTick]);
  const show = () => {
    if (denied) return;
    epoch.current++;
    reviewedGeneration.current = current.current.generation;
    setOpen(true);
    setError("");
    setReview(null);
    setValue(clone(current.current.copy));
    initial.current = JSON.stringify(current.current.copy);
    setEditing(true);
    setFuture(true);
    futureChosen.current = false;
    let saved: string | null = null;
    try {
      saved = sessionStorage.getItem(storageKey);
    } catch {
      /* Optional. */
    }
    if (saved && /^[a-f0-9]{32}$/.test(saved)) {
      setNonce(saved);
      setEditing(false);
      setRecovering(true);
      const ticket = epoch.current;
      void read(saved, ticket).finally(() => {
        if (alive.current && epoch.current === ticket) setRecovering(false);
      });
    } else {
      setNonce(null);
      setRecovering(false);
    }
  };
  const close = () => {
    if (dirty) {
      setDiscard(true);
      return false;
    }
    epoch.current++;
    setOpen(false);
    setConfirm(false);
    return true;
  };
  const preview = async () => {
    if (
      running.current ||
      !props.allowed ||
      props.generation !== reviewedGeneration.current ||
      !validPostCopy(value)
    )
      return;
    epoch.current++;
    const key = crypto.randomUUID().replaceAll("-", ""),
      ticket = epoch.current;
    running.current = true;
    setBusy(true);
    setError("");
    remember(key);
    setEditing(false);
    try {
      const next = await api<PostReview>(base, "POST", {
        nonce: key,
        generation: reviewedGeneration.current,
        candidate: value,
      });
      if (alive.current && epoch.current === ticket) accept(next);
    } catch (reason) {
      if (alive.current && epoch.current === ticket) {
        failed(reason);
        if (reason instanceof ApiError && [400, 409].includes(reason.status)) {
          remember(null);
          setEditing(true);
          if (reason.status === 409) current.current.onUpdated();
        }
      }
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const update = async () => {
    setConfirm(false);
    if (
      running.current ||
      !nonce ||
      !props.allowed ||
      review?.status !== "ready" ||
      review.has_changes !== true ||
      !review.worker_ready ||
      !review.channel_name ||
      props.generation !== reviewedGeneration.current
    )
      return;
    epoch.current++;
    const ticket = epoch.current;
    running.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await api<PostReview>(`${base}/${nonce}/update`, "POST", {
        future_months: future,
      });
      if (alive.current && epoch.current === ticket) accept(next);
    } catch (reason) {
      if (alive.current && epoch.current === ticket) {
        failed(reason);
        void read(nonce, ticket);
      }
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const editAgain = () => {
    epoch.current++;
    reviewedGeneration.current = props.generation;
    initial.current = JSON.stringify(value);
    setReview(null);
    setEditing(true);
    setError("");
    setFuture(true);
    futureChosen.current = false;
    remember(null);
  };
  const footer = editing ? (
    <button
      type="button"
      disabled={
        busy ||
        !props.allowed ||
        props.generation !== reviewedGeneration.current ||
        !validPostCopy(value)
      }
      onClick={() => void preview()}
    >
      Preview
    </button>
  ) : review?.status === "ready" ? (
    <div className="announcement-post-footer">
      <small>{future ? "This month and future months" : "This month"}</small>
      <button
        type="button"
        disabled={
          busy ||
          !props.allowed ||
          props.generation !== reviewedGeneration.current ||
          !review.worker_ready ||
          !review.channel_name ||
          review.has_changes !== true
        }
        onClick={() => setConfirm(true)}
      >
        Update post
      </button>
    </div>
  ) : undefined;
  return (
    <>
      <button
        type="button"
        ref={opener}
        disabled={!props.allowed || denied}
        onClick={show}
      >
        Edit post
      </button>
      {open && (
        <ActionPanel
          className="announcement-post-panel"
          title={`Edit ${props.pool === "main" ? "Main" : "Lazy"} roster post`}
          trigger={opener.current}
          onClose={close}
          footer={footer}
        >
          <p>Edits this post. No ping.</p>
          {error && <p role="alert">{error}</p>}
          {denied && (
            <p>
              Reload the page after signing in or restoring access to reopen
              this editor.
            </p>
          )}
          {!props.allowed && (
            <p role="alert">
              Permissions or settings changed. Refresh Announcements before
              updating.
            </p>
          )}
          {props.generation !== reviewedGeneration.current &&
            review?.status !== "done" && (
              <div>
                <p role="alert">
                  Saved settings changed. Preview against the latest settings
                  before updating.
                </p>
                {editing && (
                  <button
                    type="button"
                    disabled={busy || !props.allowed || !validPostCopy(value)}
                    onClick={() => {
                      reviewedGeneration.current = props.generation;
                      void preview();
                    }}
                  >
                    Preview against latest settings
                  </button>
                )}
              </div>
            )}
          {editing ? (
            <>
              <AnnouncementPostCopyEditor
                value={value}
                onChange={setValue}
                disabled={busy || !props.allowed}
              />
            </>
          ) : (
            <>
              {(busy || recovering) && <p role="status">Checking the post…</p>}
              {review && (
                <AnnouncementPostReview
                  key={nonce || "receipt"}
                  review={review}
                  future={future}
                  onFutureChange={(value) => {
                    futureChosen.current = true;
                    setFuture(value);
                  }}
                  canEdit={!busy && props.allowed}
                  onRefresh={() => {
                    if (nonce) void read(nonce, epoch.current);
                  }}
                  onEditAgain={editAgain}
                />
              )}
              {!review && nonce && !busy && !recovering && (
                <button
                  type="button"
                  onClick={() => void read(nonce, epoch.current)}
                >
                  Check preview
                </button>
              )}
            </>
          )}
          {confirm && review?.channel_name && (
            <ConfirmDialog
              heading="Update roster post"
              text={`Update the existing post in #${review.channel_name}? No ping or new post is sent. ${future ? "Also save this text for future months." : "Save this text for this month."}`}
              confirmLabel="Update post"
              disabled={
                busy ||
                !props.allowed ||
                props.generation !== reviewedGeneration.current
              }
              onCancel={() => setConfirm(false)}
              onConfirm={() => void update()}
            />
          )}
          {discard && (
            <ConfirmDialog
              heading="Discard text changes?"
              text="Your unpreviewed text changes will be discarded."
              confirmLabel="Discard changes"
              onCancel={() => setDiscard(false)}
              onConfirm={() => {
                setDiscard(false);
                epoch.current++;
                setOpen(false);
                setConfirm(false);
              }}
            />
          )}
        </ActionPanel>
      )}
    </>
  );
}
