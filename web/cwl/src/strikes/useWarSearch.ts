import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { errorText } from "./format";
import type { War } from "./types";

export default function useWarSearch({
  enabled,
  clan,
}: {
  enabled: boolean;
  clan: string;
}) {
  const [showWarSearch, setShowWarSearch] = useState(false);
  const warSearchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!showWarSearch) return;
    warSearchRef.current?.scrollIntoView?.({ block: "center" });
    warSearchRef.current?.focus({ preventScroll: true });
  }, [showWarSearch]);
  const [warQuery, setWarQuery] = useState("");
  const [wars, setWars] = useState<War[]>([]);
  const [warPage, setWarPage] = useState(0);
  const [warTotal, setWarTotal] = useState(0);
  const [warIncomplete, setWarIncomplete] = useState(false);
  const [warRetry, setWarRetry] = useState(0);
  const [warLoading, setWarLoading] = useState(false);
  const [warError, setWarError] = useState("");
  useEffect(() => {
    if (!enabled || !showWarSearch) return;
    let active = true;
    const timer = setTimeout(() => {
      setWarLoading(true);
      setWarError("");
      const params = new URLSearchParams({
        limit: "25",
        offset: String(warPage * 25),
      });
      if (warQuery.trim()) params.set("query", warQuery.trim());
      if (clan) params.set("clan", clan);
      void api<{
        wars: War[];
        total: number;
        name_search_incomplete?: boolean;
      }>(`/strikes/wars?${params}`)
        .then((data) => {
          if (active) {
            setWars(data.wars);
            setWarTotal(data.total);
            setWarIncomplete(!!data.name_search_incomplete);
          }
        })
        .catch((err) => {
          if (active) setWarError(errorText(err));
        })
        .finally(() => {
          if (active) setWarLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [enabled, showWarSearch, warQuery, clan, warPage, warRetry]);
  return {
    showWarSearch,
    setShowWarSearch,
    warSearchRef,
    warQuery,
    setWarQuery,
    wars,
    setWars,
    warPage,
    setWarPage,
    warTotal,
    warIncomplete,
    setWarRetry,
    warLoading,
    warError,
  };
}
