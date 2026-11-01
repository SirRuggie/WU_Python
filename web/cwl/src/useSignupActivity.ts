import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { SignupChange } from "./signupActivityModel";
export default function useSignupActivity(seasonId: string) {
  const [items, setItems] = useState<SignupChange[]>([]);
  const [error, setError] = useState(false);
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [result, setResult] = useState("");
  const [attempt, setAttempt] = useState(0);
  const submitting = useRef(false);
  const alive = useRef(true);
  const reviewed = useRef(new Set<number>());
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true,
      fetching = false,
      lastAttempt = -Infinity;
    async function load(force = false) {
      if (fetching || submitting.current || document.hidden) return;
      if (!force && Date.now() - lastAttempt < 30000) return;
      lastAttempt = Date.now();
      fetching = true;
      try {
        const response = await api<{ items: SignupChange[] }>(
          `/seasons/${encodeURIComponent(seasonId)}/signup-activity`,
        );
        if (active) {
          setItems(
            response.items.filter((item) => !reviewed.current.has(item.id)),
          );
          setError(false);
        }
      } catch {
        if (active) setError(true);
      } finally {
        fetching = false;
      }
    }
    void load(true);
    const timer = window.setInterval(() => void load(), 30000);
    const onVisibility = () => void load();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [seasonId, attempt]);
  async function review(selected: SignupChange[]) {
    if (submitting.current) return;
    submitting.current = true;
    setResult("");
    let completed = 0;
    try {
      for (const item of selected) {
        if (!alive.current) break;
        setBusy(item.id);
        setRowErrors((current) => ({ ...current, [item.id]: "" }));
        try {
          await api(
            `/seasons/${encodeURIComponent(seasonId)}/signup-activity/${item.id}/review`,
            "POST",
          );
          reviewed.current.add(item.id);
          completed++;
          if (alive.current)
            setItems((current) => current.filter((row) => row.id !== item.id));
        } catch (cause) {
          if (alive.current)
            setRowErrors((current) => ({
              ...current,
              [item.id]:
                cause instanceof Error
                  ? cause.message
                  : "Could not mark reviewed.",
            }));
          // Never retry a write automatically, including a lost response.
          break;
        }
      }
      if (alive.current && selected.length > 1)
        setResult(`Reviewed ${completed} of ${selected.length}`);
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(null);
    }
  }
  return {
    items,
    error,
    rowErrors,
    busy,
    result,
    review,
    retry: () => setAttempt((value) => value + 1),
  };
}
