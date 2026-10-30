import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Read the edit baseline before Save, never silently refresh it during a write. */
export default function useReplacementRevision(tag: string) {
  const [baseline, setBaseline] = useState<{
    tag: string;
    revision: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const normalized = tag.trim()
    ? "#" + tag.trim().replace(/^#/, "").toUpperCase()
    : "";
  const reload = useCallback(async () => {
    const id = ++generation.current;
    setBaseline(null);
    setError("");
    if (!/^#[0289PYLQGRJCUV]{3,15}$/.test(normalized)) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const result = await api<{ revision: number }>(
        `/strikes/replacement-list/${encodeURIComponent(normalized)}`,
      );
      if (id === generation.current)
        setBaseline({ tag: normalized, revision: result.revision });
    } catch (cause) {
      if (id === generation.current)
        setError(
          cause instanceof Error ? cause.message : "Could not load priority.",
        );
    } finally {
      if (id === generation.current) setLoading(false);
    }
  }, [normalized]);
  useEffect(() => {
    void reload();
    return () => {
      generation.current++;
    };
  }, [reload]);
  return {
    revision: baseline?.tag === normalized ? baseline.revision : null,
    loading,
    error,
    reload,
    tag: normalized,
  };
}
