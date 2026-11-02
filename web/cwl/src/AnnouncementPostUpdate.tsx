import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool } from "./api";
import ActionPanel from "./ActionPanel";
import ConfirmDialog from "./ConfirmDialog";
import DiscordPreview from "./DiscordMessagePreview";
import AnnouncementPostCopyEditor from "./AnnouncementPostCopyEditor";
import {
  postUpdateActive,
  safePostUrl,
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
    reviewedGeneration.current = next.generation;
    setReview(next);
    setValue(clone(next.candidate));
    setEditing(false);
    setFuture(next.future_months);
    if (next.status === "done") current.current.onUpdated();
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
    }
    setError(text(reason));
  };
  const read = async (key: string, ticket: number) => {
    try {
      const next = await api<PostReview>(`${base}/${key}`);
      if (alive.current && epoch.current === ticket) accept(next);
    } catch (reason) {
      if (alive.current && epoch.current === ticket) failed(reason);
    }
  };
  useEffect(() => {
    if (!open || !nonce || !postUpdateActive(review)) return;
    const ticket = epoch.current;
    const timer = window.setTimeout(() => {
      void read(nonce, ticket);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [open, nonce, review]);
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
    let saved: string | null = null;
    try {
      saved = sessionStorage.getItem(storageKey);
    } catch {
      /* Optional. */
    }
    if (saved && /^[a-f0-9]{32}$/.test(saved)) {
      setNonce(saved);
      void read(saved, epoch.current);
    } else setNonce(null);
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
      if (alive.current && epoch.current === ticket) failed(reason);
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
      props.generation !== reviewedGeneration.current
    )
      return;
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
    reviewedGeneration.current = props.generation;
    initial.current = JSON.stringify(value);
    setReview(null);
    setEditing(true);
    setError("");
    setFuture(true);
    remember(null);
  };
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
          title={`Edit ${props.pool === "main" ? "Main" : "Lazy"} roster post`}
          trigger={opener.current}
          onClose={close}
        >
          <p>
            Update the same Discord post in place. Images, destination and
            notification roles stay unchanged. This update sends no ping.
          </p>
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
              <p role="alert">
                Saved campaign changed. Refresh Announcements and preview again
                before updating.
              </p>
            )}
          {editing ? (
            <>
              <AnnouncementPostCopyEditor
                value={value}
                onChange={setValue}
                disabled={busy || !props.allowed}
              />
              <p>
                Preview changes no post or saved campaign. A successful update
                saves this pool’s current-month text and buttons.
              </p>
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
            </>
          ) : (
            <>
              {busy && <p role="status">Checking the post…</p>}
              {review && (
                <>
                  {review.live_preview && review.draft_preview && (
                    <div className="announcement-post-comparison">
                      <DiscordPreview
                        label="Live post at preview"
                        parts={review.live_preview}
                      />
                      <DiscordPreview
                        label="Proposed update"
                        parts={review.draft_preview}
                      />
                    </div>
                  )}
                  {postUpdateActive(review) && (
                    <p role="status">
                      {["pending_preview", "previewing"].includes(review.status)
                        ? "Preparing preview…"
                        : "Updating the reviewed post…"}{" "}
                      You can close this panel and reopen it to check the
                      result.
                    </p>
                  )}
                  {review.error && <p role="alert">{review.error}</p>}
                  {review.status === "expired" && (
                    <p role="alert">Preview expired. Preview again.</p>
                  )}
                  {review.status === "ready" && (
                    <>
                      <label className="announcement-post-future">
                        <input
                          type="checkbox"
                          checked={future}
                          onChange={(e) => setFuture(e.target.checked)}
                        />
                        Also use for future months
                      </label>
                      <p>
                        {future
                          ? "Also saves only this pool’s recurring roster text and buttons. Other messages are unchanged."
                          : "Only this month’s saved roster copy changes. Its existing future-month copy stays as it is."}
                      </p>
                      {!review.worker_ready && (
                        <>
                          <p role="status">
                            The bot editor is reconnecting. Check the preview
                            again before updating.
                          </p>
                          <button
                            type="button"
                            onClick={() =>
                              nonce && void read(nonce, epoch.current)
                            }
                          >
                            Refresh status
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        disabled={
                          busy ||
                          !props.allowed ||
                          props.generation !== reviewedGeneration.current ||
                          !review.worker_ready ||
                          !review.channel_name
                        }
                        onClick={() => setConfirm(true)}
                      >
                        Update post
                      </button>
                    </>
                  )}
                  {review.status === "done" && (
                    <>
                      <p role="status">
                        Post updated.
                        {review.campaign_saved
                          ? ` Saved for this month${review.recurring_saved ? " and future months" : ""}.`
                          : ""}
                      </p>
                      {review.save_warning && (
                        <p role="alert">{review.save_warning}</p>
                      )}
                    </>
                  )}
                  {review.error_code !== "deleted" &&
                    safePostUrl(review.message_url) && (
                      <a
                        href={review.message_url!}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {review.status === "uncertain"
                          ? "Check post"
                          : "Open post"}
                      </a>
                    )}
                  {review.error_code !== "deleted" &&
                    !postUpdateActive(review) && (
                      <button
                        type="button"
                        disabled={busy || !props.allowed}
                        onClick={editAgain}
                      >
                        {review.status === "done"
                          ? "Edit again"
                          : "Preview again"}
                      </button>
                    )}
                </>
              )}
              {!review && nonce && !busy && (
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
              text={`Update the existing post in #${review.channel_name}? No ping or new post is sent.`}
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
