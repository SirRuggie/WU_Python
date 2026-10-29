import useLocationNow from "./useLocationNow";
import {
  comparisonPoolMemory,
  type ComparisonMemory,
} from "./comparisonMemory";
import { useEffect, useRef, useState } from "react";
import { createComparisonChecks } from "./comparisonChecks";
import { mergeComparisonLocations } from "./comparisonLocation";

import { readArrival } from "./locationTransport";
export type {
  PublishedComparisonAccount,
  ArrivalResponse,
} from "./locationTransport";

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
  const [now, setNow] = useLocationNow();
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
          if (!signal.aborted || signal.reason?.name === "TimeoutError") {
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
    return () => {
      runner.dispose();
      checks.current = null;
      document.removeEventListener("visibilitychange", visibility);
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
