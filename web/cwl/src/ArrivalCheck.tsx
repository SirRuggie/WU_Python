import { useMemo } from "react";
import useDeclarationData from "./useDeclarationData";
import { declarationSnapshot } from "./declarationData";
import useStaffDetailsPage from "./useStaffDetailsPage";
import StaffPlayerButton from "./StaffPlayerButton";
import { hiddenPublicationStatus } from "./publicationStatus";
import { Button } from "./rosterUi/primitives";
import "./ArrivalCheck.css";
export default function ArrivalCheck({ seasonId }: { seasonId: string }) {
  const { data, error, refresh } = useDeclarationData(seasonId);
  const published =
    !!data?.publication.published &&
    data.arrival.source === "published" &&
    data.arrival.publication_available;
  const context = useMemo(
    () =>
      data && published
        ? {
            roster: declarationSnapshot(data),
            version: data.arrival.version!,
            signupTags: data.roster.accounts.map((a) => a.tag),
          }
        : undefined,
    [data, published],
  );
  useStaffDetailsPage({
    enabled: !!context,
    seasonId,
    viewOnly: "declaration",
    publishedSnapshot: context,
    order: context?.roster.accounts.map((a) => a.tag),
  });
  return (
    <section
      className="arrival-check roster-ui"
      aria-label="Declaration readiness"
    >
      {error && (
        <p role="alert">
          {error} <Button onClick={refresh}>Refresh</Button>
        </p>
      )}
      {!data && <p role="status">Checking published roster…</p>}
      {data && !published && (
        <p>
          {data.publication.last_publication?.withdrawn_at
            ? hiddenPublicationStatus(data.publication.last_publication)
            : "Publish the roster first"}{" "}
          ·{" "}
          <a href={`/cwl/publish?season=${seasonId}&step=review`}>
            Finalize roster ›
          </a>
        </p>
      )}
      {data && published && (
        <>
          {data.arrival.publication_outdated && (
            <p>
              Checking published version {data.arrival.version} · the draft has
              changes members can't see yet
            </p>
          )}
          {context?.roster.accounts.map((a) => (
            <StaffPlayerButton
              key={a.tag}
              seasonId={seasonId}
              tag={a.tag}
              viewOnly="declaration"
              publishedSnapshot={context}
              order={context.roster.accounts.map((x) => x.tag)}
            >
              {a.player_name}
            </StaffPlayerButton>
          ))}
        </>
      )}
    </section>
  );
}
