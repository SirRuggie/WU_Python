import { useEffect, useState } from "react";
import { api } from "./api";
export function useReminderLookup<T>(path: string, field: string) {
  const [items, setItems] = useState<T[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<Record<string, T[]>>(path)
      .then((data) => {
        if (active) setItems(data[field]);
      })
      .catch((error) => {
        if (active) {
          setItems([]);
          setError(
            error instanceof Error ? error.message : "Could not load options.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [path, field, attempt]);
  return {
    items,
    error,
    loading,
    retry: () => setAttempt((value) => value + 1),
  };
}
