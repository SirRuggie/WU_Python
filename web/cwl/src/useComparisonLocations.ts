import { useEffect, useRef, useState } from "react";
import { createComparisonChecks } from "./comparisonChecks";
import {
  mergeComparisonLocations,
  type ComparisonLocation,
  type LocationRecords,
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
  const response = await fetch(
    `/api/cwl/seasons/${encodeURIComponent(season)}/arrival-check?source=${published ? "published" : "draft"}&background=1${force ? "&refresh=1" : ""}`,
    { credentials: "same-origin", signal },
  );
  if (!response.ok) {
    if (response.status === 401 || response.status === 403)
      window.dispatchEvent(new Event("dashboard-access-changed"));
    throw new Error("Location check failed");
  }
  return response.json();
}

export function useComparisonLocations(
  season: string,
  pool: string,
  hasClans: boolean,
  revision: number,
  refreshKey: number,
) {
  const [records, setRecords] = useState<LocationRecords>({});
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [checkedAt, setCheckedAt] = useState<number>();
  const [published, setPublished] = useState<
    PublishedComparisonAccount[] | null
  >(null);
  const checks = useRef<ReturnType<typeof createComparisonChecks> | null>(null);
  const enabled = useRef(hasClans);
  enabled.current = hasClans;

  useEffect(() => {
    setRecords({});
    setError("");
    setCheckedAt(undefined);
  }, [season]);
  useEffect(() => {
    const runner = createComparisonChecks(async (force, signal) => {
      try {
        const result = await readArrival(season, false, force, signal);
        if (signal.aborted) return false;
        setRecords((previous) =>
          mergeComparisonLocations(previous, result.accounts),
        );
        setError("");
        setNow(Date.now());
        setCheckedAt(Date.now());
        return result.updating;
      } catch (cause) {
        if (!signal.aborted)
          setError("Couldn't update locations · showing last results");
        throw cause;
      }
    }, setChecking);
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
  }, [season, pool]);
  useEffect(() => {
    checks.current?.setActive(
      hasClans && document.visibilityState === "visible",
    );
  }, [hasClans]);
  useEffect(() => {
    const controller = new AbortController();
    void readArrival(season, true, false, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted)
          setPublished(result.source === "published" ? result.accounts : null);
      })
      .catch(() => {
        /* Retain last published context during an ordinary read failure. */
      });
    return () => controller.abort();
  }, [season, revision, refreshKey]);
  return {
    records,
    checking,
    error,
    now,
    checkedAt,
    published,
    refresh: () => checks.current?.refresh(),
  };
}
