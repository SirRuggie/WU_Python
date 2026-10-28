import { useEffect, useRef, useState } from "react";
import { handleAuthorizationFailure } from "./api";
import { fetchReadWithRetry } from "./readRetry";
import { readArrival } from "./locationTransport";
import { createComparisonChecks } from "./comparisonChecks";
import {
  mergeComparisonLocations,
  type LocationRecords,
} from "./comparisonLocation";
import useLocationNow from "./useLocationNow";
import type { DeclarationArrival, DeclarationData } from "./declarationData";

async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetchReadWithRetry(url, {
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    handleAuthorizationFailure(response.status);
    throw new Error("Could not read declaration");
  }
  return response.json();
}
export default function useDeclarationData(season: string) {
  const [data, setData] = useState<DeclarationData | null>(null);
  const [records, setRecords] = useState<LocationRecords>({});
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [checkedAt, setCheckedAt] = useState<number>();
  const [now, setNow] = useLocationNow();
  const runner = useRef<ReturnType<typeof createComparisonChecks> | null>(null);
  useEffect(() => {
    setData(null);
    setRecords({});
    setCheckedAt(undefined);
    setError("");
    const path = `/api/cwl/seasons/${encodeURIComponent(season)}`;
    const checks = createComparisonChecks(
      async (force, signal) => {
        try {
          const [arrival, roster, publication] = await Promise.all([
            readArrival(
              season,
              true,
              force,
              signal,
            ) as Promise<DeclarationArrival>,
            read<DeclarationData["roster"]>(`${path}/roster`, signal),
            read<DeclarationData["publication"]>(`${path}/publication`, signal),
          ]);
          if (signal.aborted) return false;
          setData({ arrival, roster, publication });
          setRecords((previous) =>
            mergeComparisonLocations(previous, arrival.accounts),
          );
          setError("");
          setCheckedAt(Date.now());
          setNow(Date.now());
          return false;
        } catch (cause) {
          if (!signal.aborted || signal.reason?.name === "TimeoutError")
            setError("Couldn't update · showing last results");
          throw cause;
        }
      },
      setChecking,
      -Infinity,
      () => {},
      false,
    );
    runner.current = checks;
    const visibility = () =>
      checks.setActive(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", visibility);
    visibility();
    return () => {
      checks.dispose();
      runner.current = null;
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [season]);
  return {
    data,
    records,
    error,
    checking,
    checkedAt,
    now,
    refresh: () => runner.current?.refresh(),
  };
}
