import { fetchReadWithRetry } from "./readRetry";
import { handleAuthorizationFailure } from "./api";
import {
  comparisonPoolMemory,
  type ComparisonMemory,
} from "./comparisonMemory";
import { useEffect, useRef, useState } from "react";
import { createComparisonChecks } from "./comparisonChecks";
import {
  mergeComparisonLocations,
  type ComparisonLocation,
} from "./comparisonLocation";

export type PublishedComparisonAccount = {
  tag: string;
  assigned_clan_tag: string | null;
  assigned_clan_name: string | null;
};
export type ArrivalResponse = {
  source: "draft" | "published";
  updating: boolean;
  accounts: (ComparisonLocation & PublishedComparisonAccount)[];
};

// Read-only transport: an offline Compare read must not POST diagnostic reports.
async function readArrival(
  season: string,
  published: boolean,
  force: boolean,
  signal: AbortSignal,
): Promise<ArrivalResponse> {
  const response = await fetchReadWithRetry(
    `/api/cwl/seasons/${encodeURIComponent(season)}/arrival-check?source=${published ? "published" : "draft"}&background=1${force ? "&refresh=1" : ""}`,
    { credentials: "same-origin", signal },
  );
  if (!response.ok) {
    handleAuthorizationFailure(response.status);
    throw new Error("Location check failed");
  }
  return response.json();
}

export function useComparisonLocations(
  memory: ComparisonMemory,
  season: string,
  pool: string,
  hasClans: boolean,
  revision: number,
  refreshKey: number,
) {
  const cache = comparisonPoolMemory(memory, pool);
  const publication = memory.publication;
  const [, redraw] = useState(0);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const checks = useRef<ReturnType<typeof createComparisonChecks> | null>(null);
  const enabled = useRef(hasClans);
  enabled.current = hasClans;

  useEffect(() => {
    setError("");
    const runner = createComparisonChecks(
      async (force, signal) => {
        try {
          const result = await readArrival(season, false, force, signal);
          if (signal.aborted) return false;
          memory.records = mergeComparisonLocations(
            memory.records,
            result.accounts,
          );
          redraw((value) => value + 1);
          setError("");
          setNow(Date.now());
          cache.checkedAt = Date.now();
          return result.updating;
        } catch (cause) {
          if (!signal.aborted) {
            setError("Couldn't update locations · showing last results");
          }
          throw cause;
        }
      },
      setChecking,
      cache.lastCheck,
      (time) => {
        cache.lastCheck = time;
      },
    );
    checks.current = runner;
    const visibility = () =>
      runner.setActive(
        enabled.current && document.visibilityState === "visible",
      );
    document.addEventListener("visibilitychange", visibility);
    visibility();
    const clock = setInterval(() => {
      if (document.visibilityState === "visible") setNow(Date.now());
    }, 30_000);
    return () => {
      runner.dispose();
      checks.current = null;
      document.removeEventListener("visibilitychange", visibility);
      clearInterval(clock);
    };
  }, [season, pool, memory]);
  useEffect(() => {
    checks.current?.setActive(
      hasClans && document.visibilityState === "visible",
    );
  }, [hasClans]);
  useEffect(() => {
    if (
      !hasClans ||
      (publication.publicationRevision === revision &&
        publication.publicationRefresh === refreshKey &&
        Date.now() - publication.publicationAt < 300_000)
    )
      return;
    const controller = new AbortController();
    void readArrival(season, true, false, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          publication.published =
            result.source === "published" ? result.accounts : null;
          publication.publicationAt = Date.now();
          publication.publicationRevision = revision;
          publication.publicationRefresh = refreshKey;
          redraw((value) => value + 1);
        }
      })
      .catch(() => {
        /* Retain last published context during an ordinary read failure. */
      });
    return () => controller.abort();
  }, [season, pool, memory, revision, refreshKey, hasClans]);
  return {
    records: memory.records,
    checking,
    error,
    now,
    checkedAt: cache.checkedAt,
    published: publication.published,
    refresh: () => checks.current?.refresh(),
  };
}
