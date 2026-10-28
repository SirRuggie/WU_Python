import DeclarationPlayerCard from "./DeclarationPlayerCard";
import { declarationGroups } from "./declarationGroups";
import { useMemo } from "react";
import useDeclarationData from "./useDeclarationData";
import { declarationSnapshot } from "./declarationData";
import useStaffDetailsPage from "./useStaffDetailsPage";

import { hiddenPublicationStatus } from "./publicationStatus";
import { Button } from "./rosterUi/primitives";
import "./ArrivalCheck.css";
export default function ArrivalCheck({ seasonId }: { seasonId: string }) {
  const { data, error, refresh, records, now } = useDeclarationData(seasonId);
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
          {context &&
            declarationGroups(data, context.roster, records, now).map(
              (group) => (
                <section key={group.key}>
                  <h2>
                    {group.name} ·{" "}
                    {group.readiness.ready ? "Ready" : "Not ready"} ·{" "}
                    {group.readiness.arrivedCount}/{group.capacity ?? "—"} in
                    clan
                  </h2>
                  {group.accounts.map((account) => (
                    <DeclarationPlayerCard
                      key={account.tag}
                      account={account}
                      clanName={group.name}
                      record={records[account.tag]}
                      now={now}
                      request={{
                        seasonId,
                        viewOnly: "declaration",
                        publishedSnapshot: context,
                        order: group.accounts.map((a) => a.tag),
                      }}
                    />
                  ))}
                </section>
              ),
            )}
        </>
      )}
    </section>
  );
}
