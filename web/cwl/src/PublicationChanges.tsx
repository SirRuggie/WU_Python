import { useEffect, useState } from "react";
import { api } from "./api";
import type { PublicationDraft } from "./publication";
import {
  publicationChanges,
  type PublishedAccount,
} from "./publicationAwareness";
import "./publicationAwareness.css";
export default function PublicationChanges({
  seasonId,
  draft,
  onReady,
}: {
  seasonId: string;
  draft: PublicationDraft;
  onReady: (ready: boolean) => void;
}) {
  const [result, setResult] = useState<ReturnType<
    typeof publicationChanges
  > | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let active = true;
    setResult(null);
    setExpanded(false);
    setError("");
    onReady(false);
    if (!draft.published) {
      setResult(publicationChanges(draft, []));
      onReady(true);
      return;
    }
    void api<{
      rows: PublishedAccount[];
      summary: { published_version: number };
    }>(
      `/seasons/${encodeURIComponent(seasonId)}/export-preview?kind=accounts&basis=published`,
    )
      .then((snapshot) => {
        if (!active) return;
        if (snapshot.summary.published_version !== draft.published?.version)
          throw new Error(
            "Published version changed. Refresh Finalize before reviewing.",
          );
        setResult(publicationChanges(draft, snapshot.rows));
        onReady(true);
      })
      .catch((cause) => {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Couldn't load placement changes.",
          );
      });
    return () => {
      active = false;
    };
  }, [seasonId, draft, onReady]);
  return (
    <section
      className="publication-change-list"
      aria-label="Changes to publish"
    >
      <h3>Publishing creates version {draft.next_version}</h3>
      <p>For Main and Lazy · no Discord message is sent</p>
      {error ? (
        <p role="alert">{error} Use Refresh draft to try again.</p>
      ) : !result ? (
        <p role="status">Loading changes…</p>
      ) : (
        <>
          <ul>
            {(expanded ? result.lines : result.lines.slice(0, 4)).map(
              (line) => (
                <li key={line.tag}>
                  <strong>{line.name}</strong>
                  <span>{line.text}</span>
                </li>
              ),
            )}
          </ul>
          {!expanded && result.lines.length > 4 && (
            <button type="button" onClick={() => setExpanded(true)}>
              Show all {result.lines.length} changes ›
            </button>
          )}
          {draft.draft_changed && (
            <p className="publication-change-caveat">
              Also included: any weight or signup-detail changes not listed
              above.
            </p>
          )}
          {!result.lines.length && !draft.draft_changed && (
            <p>No placement changes.</p>
          )}
        </>
      )}
    </section>
  );
}
