import type { PublicationDraft, PublicationMeta } from "./publication";
import { publicationReviewLabel } from "./publicationAwareness";
import "./publicationAwareness.css";
const shortDate = (value: string) =>
  new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
export default function PublicationAwarenessBanner({
  published,
  lastPublication = null,
  changed,
  canPublish,
  onReview,
  disabled = false,
}: {
  published: PublicationMeta | null;
  lastPublication?: PublicationDraft["last_publication"];
  changed: boolean;
  canPublish: boolean;
  onReview?: () => void;
  disabled?: boolean;
}) {
  const label = publicationReviewLabel(canPublish, !!onReview);
  const status = published
    ? changed
      ? `Members see v${published.version} ${shortDate(published.published_at)} · Draft changes unpublished`
      : `Published · v${published.version} · ${shortDate(published.published_at)} · Members can see it`
    : lastPublication?.withdrawn_at
      ? `Hidden from members · v${lastPublication.version} ${shortDate(lastPublication.published_at)}`
      : "Draft · not published yet";
  return (
    <aside
      className="publication-awareness"
      aria-label="Placement publication status"
    >
      <span className="publication-awareness-status">{status}</span>
      {changed || !published ? (
        label ? (
          <button
            type="button"
            onClick={onReview}
            disabled={disabled}
            aria-label={label}
          >
            Review ›
          </button>
        ) : (
          <span>Ask a staff member with publish access.</span>
        )
      ) : null}
    </aside>
  );
}
