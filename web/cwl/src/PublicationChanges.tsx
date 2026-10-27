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
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setResult(null);
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
  }, [seasonId, draft, attempt, onReady]);
  return (
    <section
      className="publication-change-list"
      aria-label="Changes to publish"
    >
      <h3>Publishing creates version {(draft.published?.version ?? 0) + 1}</h3>
      <p>
        From the current draft, for Main and Lazy. Members will see these
        placement changes. No Discord message is sent.
      </p>
      {error ? (
        <p role="alert">
          {error}{" "}
          <button onClick={() => setAttempt((value) => value + 1)}>
            Retry changes
          </button>
        </p>
      ) : !result ? (
        <p role="status">Loading changes…</p>
      ) : (
        <>
          <ul>
            {result.lines.map((line) => (
              <li key={line.tag}>
                <strong>{line.name}</strong>
                <span>{line.text}</span>
              </li>
            ))}
          </ul>
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
