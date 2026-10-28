import { publicationDate, hiddenPublicationStatus } from "./publicationStatus";
import type { PublicationDraft, PublicationMeta } from "./publication";
import { publicationReviewLabel } from "./publicationAwareness";
import "./publicationAwareness.css";
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
  if (published && !changed) return null;
  const label = publicationReviewLabel(canPublish, !!onReview);
  return (
    <aside
      className="publication-awareness"
      aria-label="Placement publication status"
    >
      <div>
        <strong>
          {published
            ? `Members still see roster version ${published.version}`
            : lastPublication?.withdrawn_at
              ? hiddenPublicationStatus(lastPublication)
              : "Draft · members can't see placements yet"}
        </strong>
        {published && (
          <p>
            <span className="publication-awareness-date">
              Published {publicationDate(published.published_at)}.
            </span>{" "}
            Placement changes made since then are draft only.
          </p>
        )}
      </div>
      {label ? (
        <button type="button" onClick={onReview} disabled={disabled}>
          {label}
        </button>
      ) : (
        <p>Ask a staff member with publish access.</p>
      )}
    </aside>
  );
}
