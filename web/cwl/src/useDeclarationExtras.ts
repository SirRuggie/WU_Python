import {
  patchDeclarationMark,
  patchDeclarationMarks,
} from "./declarationMarks";
import type { FillerSaveResult } from "./RosterFillerCheckbox";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { DeclarationExtraResponse } from "./declarationExtras";

/** A single explicit page-load/Refresh read. No periodic or visibility polling. */
export default function useDeclarationExtras(
  season: string,
  source: "draft" | "published",
  basis: number | null,
  enabled: boolean,
) {
  const [data, setData] = useState<DeclarationExtraResponse>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshNonce, setRefreshNonce] = useState(0);
  const sequence = useRef(0);
  const explicitRead = useRef(0);
  const [refreshResult, setRefreshResult] = useState<{
    id: number;
    status: "pending" | "success" | "failed";
  } | null>(null);
  useEffect(() => {
    const current = ++sequence.current;
    const controller = new AbortController();
    let disposed = false;
    setData(undefined);
    setError("");
    setLoading(enabled && basis !== null);
    if (!enabled || basis === null)
      return () => {
        disposed = true;
        controller.abort();
      };
    const timer = setTimeout(() => controller.abort(), 45000);
    void api<DeclarationExtraResponse>(
      `/seasons/${season}/declaration-extras?source=${source}&basis=${basis}${refreshNonce ? "&refresh=1" : ""}`,
      "GET",
      undefined,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!disposed && current === sequence.current) {
          if (result.source !== source || result.basis !== basis)
            throw new Error(
              "Roster changed. Refresh the page before checking members.",
            );
          setData(result);
          if (refreshNonce)
            setRefreshResult((current) =>
              current?.id === refreshNonce && current.status === "pending"
                ? { id: refreshNonce, status: "success" }
                : current,
            );
        }
      })
      .catch(() => {
        if (!disposed && current === sequence.current) {
          setData(undefined);
          setError("Couldn't check clan members");
          if (refreshNonce)
            setRefreshResult((current) =>
              current?.id === refreshNonce && current.status === "pending"
                ? { id: refreshNonce, status: "failed" }
                : current,
            );
        }
      })
      .finally(() => {
        clearTimeout(timer);
        if (!disposed && current === sequence.current) setLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [season, source, basis, enabled, refreshNonce]);
  return {
    data,
    loading,
    error,
    applyMark: (saved: FillerSaveResult) =>
      setData((current) =>
        current ? patchDeclarationMark(current, saved) : current,
      ),
    applyMarks: (saves: FillerSaveResult[]) =>
      setData((current) =>
        current ? patchDeclarationMarks(current, saves) : current,
      ),
    refreshResult,
    refresh: () => {
      const id = ++explicitRead.current;
      setRefreshResult({ id, status: "pending" });
      setRefreshNonce(id);
      return id;
    },
  };
}
