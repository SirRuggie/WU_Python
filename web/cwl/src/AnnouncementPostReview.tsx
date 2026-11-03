import { useState } from "react";
import DiscordPreview from "./DiscordMessagePreview";
import {
  postUpdateActive,
  safePostUrl,
  type PostReview,
} from "./announcementPostUpdate";
type Props = {
  review: PostReview;
  future: boolean;
  onFutureChange: (value: boolean) => void;
  canEdit: boolean;
  onRefresh: () => void;
  onEditAgain: () => void;
};
export default function AnnouncementPostReview({
  review,
  future,
  onFutureChange,
  canEdit,
  onRefresh,
  onEditAgain,
}: Props) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const comparison =
    review?.live_preview && review.draft_preview ? (
      <div className="announcement-post-comparison">
        <DiscordPreview
          label="Live post at preview"
          parts={review.live_preview}
        />
        <DiscordPreview label="Proposed update" parts={review.draft_preview} />
      </div>
    ) : null;

  return (
    <>
      {review.status === "ready" && (
        <>
          <label className="announcement-post-future">
            <input
              type="checkbox"
              checked={future}
              onChange={(e) => onFutureChange(e.target.checked)}
            />
            Also use for future months
          </label>
          {review.has_changes === false && <p role="status">No changes</p>}
          {review.has_changes === undefined && (
            <p role="status">Preview again.</p>
          )}
          {!review.worker_ready && (
            <>
              <p role="status">
                The bot editor is reconnecting. Check the preview again before
                updating.
              </p>
              <button type="button" onClick={onRefresh}>
                Refresh status
              </button>
            </>
          )}
        </>
      )}
      {postUpdateActive(review) && (
        <p role="status">
          {["pending_preview", "previewing"].includes(review.status)
            ? "Preparing preview…"
            : "Updating…"}{" "}
          You can close this panel and reopen it to check the result.
        </p>
      )}
      {postUpdateActive(review) && (
        <button type="button" onClick={onRefresh}>
          Refresh status
        </button>
      )}

      {review.error && <p role="alert">{review.error}</p>}
      {review.status === "expired" && (
        <p role="alert">Preview expired. Preview again.</p>
      )}
      {review.status === "done" && (
        <>
          <p role="status">
            Post updated.
            {review.campaign_saved
              ? ` Saved for this month${review.recurring_saved ? " and future months" : ""}.`
              : ""}
          </p>
          {review.save_warning && <p role="alert">{review.save_warning}</p>}
        </>
      )}
      {review.error_code !== "deleted" && safePostUrl(review.message_url) && (
        <a
          className="announcement-post-link announcement-result-link"
          href={review.message_url!}
          target="_blank"
          rel="noreferrer"
        >
          {review.status === "uncertain" ? "Check post" : "Open post"}
        </a>
      )}
      {review.error_code !== "deleted" && !postUpdateActive(review) && (
        <button type="button" disabled={!canEdit} onClick={onEditAgain}>
          {review.status === "done" ? "Edit again" : "Preview again"}
        </button>
      )}
      {comparison &&
        (review.status === "ready" ? (
          comparison
        ) : (
          <details
            onToggle={(event) => setHistoryOpen(event.currentTarget.open)}
          >
            <summary>Earlier preview</summary>
            {historyOpen && comparison}
          </details>
        ))}
    </>
  );
}
